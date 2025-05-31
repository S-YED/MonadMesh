# orchestrator.py
import asyncio
from typing import Dict, List, Optional
from pymongo import MongoClient
from bson import ObjectId
import json
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MonadOrchestrator:
    def __init__(self, mongo_uri: str = "mongodb://localhost:27017"):
        self.mongo_client = MongoClient(mongo_uri)
        self.db = self.mongo_client["monadmesh"]
        self.functions = self.db["functions"]
        self.tasks = self.db["tasks"]
        self.results = self.db["results"]
        self.nodes = self.db["nodes"]  # Track available P2P nodes
        
        # Thread pool for parallel execution
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # Task queue for pending executions
        self.task_queue = asyncio.Queue()
        
        # Start background task processor
        asyncio.create_task(self._process_tasks())

    async def submit_function(self, function_data: Dict) -> str:
        """Store function and create initial task"""
        function_id = self.functions.insert_one(function_data).inserted_id
        task_data = {
            "function_id": str(function_id),
            "status": "pending",
            "submitted_by": function_data.get("owner"),
            "submitted_at": datetime.utcnow(),
            "dependencies": function_data.get("dependencies", [])
        }
        task_id = self.tasks.insert_one(task_data).inserted_id
        await self.task_queue.put(str(task_id))
        return str(task_id)

    async def _process_tasks(self):
        """Continuous task processor (runs in background)"""
        while True:
            task_id = await self.task_queue.get()
            try:
                await self._execute_task(task_id)
            except Exception as e:
                logger.error(f"Task {task_id} failed: {str(e)}")
                self.tasks.update_one(
                    {"_id": ObjectId(task_id)},
                    {"$set": {"status": "failed", "error": str(e)}}
                )

    async def _execute_task(self, task_id: str):
        """Execute a task with dependency resolution"""
        task = self.tasks.find_one({"_id": ObjectId(task_id)})
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        # Check dependencies
        deps_ready = await self._check_dependencies(task["dependencies"])
        if not deps_ready:
            logger.info(f"Task {task_id} waiting for dependencies")
            await asyncio.sleep(1)
            await self.task_queue.put(task_id)
            return
        
        # Mark as executing
        self.tasks.update_one(
            {"_id": ObjectId(task_id)},
            {"$set": {"status": "executing", "started_at": datetime.utcnow()}}
        )
        
        try:
            # Get function code
            function = self.functions.find_one({"_id": ObjectId(task["function_id"])})
            if not function:
                raise ValueError("Function not found")
            
            # Execute (in real implementation this would dispatch to P2P nodes)
            result = await self._execute_in_threadpool(
                function["code"],
                await self._get_dependency_values(task["dependencies"])
            )
            
            # Store result
            result_id = self.results.insert_one({
                "task_id": task_id,
                "output": result,
                "executed_at": datetime.utcnow()
            }).inserted_id
            
            # Mark task complete
            self.tasks.update_one(
                {"_id": ObjectId(task_id)},
                {"$set": {
                    "status": "completed",
                    "completed_at": datetime.utcnow(),
                    "result_id": str(result_id)
                }}
            )
            
            logger.info(f"Task {task_id} completed successfully")
            
        except Exception as e:
            self.tasks.update_one(
                {"_id": ObjectId(task_id)},
                {"$set": {"status": "failed", "error": str(e)}}
            )
            raise

    async def _check_dependencies(self, dependency_ids: List[str]) -> bool:
        """Verify all dependencies are completed"""
        if not dependency_ids:
            return True
            
        pending = self.tasks.count_documents({
            "_id": {"$in": [ObjectId(dep) for dep in dependency_ids]},
            "status": {"$ne": "completed"}
        })
        
        return pending == 0

    async def _get_dependency_values(self, dependency_ids: List[str]) -> Dict[str, any]:
        """Retrieve outputs from dependent tasks"""
        if not dependency_ids:
            return {}
            
        results = {}
        for dep_id in dependency_ids:
            dep_task = self.tasks.find_one({"_id": ObjectId(dep_id)})
            if not dep_task or "result_id" not in dep_task:
                raise ValueError(f"Dependency {dep_id} not completed")
                
            result = self.results.find_one({"_id": ObjectId(dep_task["result_id"])})
            if not result:
                raise ValueError(f"Result for {dep_id} not found")
                
            results[dep_id] = result["output"]
            
        return results

    async def _execute_in_threadpool(self, code: str, inputs: Dict) -> any:
        """Execute function code in threadpool (simulated)"""
        loop = asyncio.get_running_loop()
        
        # In real implementation this would:
        # 1. Serialize function + inputs
        # 2. Distribute to P2P node
        # 3. Await result
        
        def _execute():
            # Simulated execution
            logger.info(f"Executing with inputs: {inputs}")
            
            # In a real system this would use a secure sandbox
            try:
                # WARNING: Never use eval() in production!
                # This is just for demonstration
                namespace = {"inputs": inputs}
                exec(code, namespace)
                return namespace.get("result", None)
            except Exception as e:
                logger.error(f"Execution failed: {str(e)}")
                raise
            
        return await loop.run_in_executor(self.executor, _execute)

    async def get_task_status(self, task_id: str) -> Dict:
        """Get current task status"""
        task = self.tasks.find_one({"_id": ObjectId(task_id)})
        if not task:
            raise ValueError("Task not found")
            
        return {
            "status": task["status"],
            "function_id": task["function_id"],
            "submitted_at": task["submitted_at"],
            "started_at": task.get("started_at"),
            "completed_at": task.get("completed_at"),
            "error": task.get("error")
        }

    async def get_task_result(self, task_id: str) -> any:
        """Retrieve task execution result"""
        task = self.tasks.find_one({"_id": ObjectId(task_id)})
        if not task or "result_id" not in task:
            raise ValueError("Task not completed or result not available")
            
        result = self.results.find_one({"_id": ObjectId(task["result_id"])})
        if not result:
            raise ValueError("Result not found")
            
        return result["output"]

    async def register_node(self, node_id: str, capabilities: List[str]):
        """Register a P2P node as available for work"""
        self.nodes.update_one(
            {"node_id": node_id},
            {"$set": {
                "capabilities": capabilities,
                "last_seen": datetime.utcnow(),
                "active": True
            }},
            upsert=True
        )

    async def find_available_node(self, requirements: List[str]) -> Optional[str]:
        """Find a node matching execution requirements"""
        node = self.nodes.find_one({
            "active": True,
            "capabilities": {"$all": requirements}
        }, sort=[("last_seen", -1)])
        
        return node["node_id"] if node else None

# Singleton instance
orchestrator = MonadOrchestrator()