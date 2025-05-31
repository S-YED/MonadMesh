import uuid
import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from web3 import Web3
from celery import Celery
import redis
import libp2p
import wasmer
from wasmer import engine, Store, Module, Instance
import logging
from typing import List, Optional
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("monadmesh")

# Initialize FastAPI
app = FastAPI(title="MonadMesh Backend",
             description="Decentralized Serverless Functions with P2P Parallel Execution",
             version="1.0.0")

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Redis
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    db=int(os.getenv("REDIS_DB", 0))
)

# Initialize Celery
celery = Celery(
    'monadmesh_tasks',
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
)

# Initialize Web3 (Monad)
w3 = Web3(Web3.HTTPProvider(os.getenv("MONAD_RPC_URL", "https://rpc.monad.xyz")))
if not w3.is_connected():
    logger.error("Failed to connect to Monad RPC")
    raise RuntimeError("Monad RPC connection failed")

# Load contract ABI
with open('MonadMeshABI.json') as f:
    CONTRACT_ABI = json.load(f)

contract = w3.eth.contract(
    address=os.getenv("CONTRACT_ADDRESS"),
    abi=CONTRACT_ABI
)

# Initialize libp2p node
p2p_node = libp2p.Host(
    libp2p.SecurityOptions.noise,
    enable_relay=True,
    enable_dht=True
)

# WASM Engine
store = Store(engine.JIT())
wasm_cache = {}

# Models
class FunctionSubmission(BaseModel):
    code: str  # WASM binary (base64) or Python code
    inputs: List[str]
    use_zk: bool = False
    language: str = "wasm"  # or "python"

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: Optional[str]
    tx_hash: Optional[str]
    executors: List[str]

# WebSocket Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                self.disconnect(connection)

manager = ConnectionManager()

# P2P Network Functions
async def connect_to_bootstrap_nodes():
    bootstrap_nodes = [
        "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ",
        "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN"
    ]
    
    for node in bootstrap_nodes:
        try:
            await p2p_node.connect(node)
            logger.info(f"Connected to bootstrap node: {node}")
        except Exception as e:
            logger.warning(f"Failed to connect to {node}: {str(e)}")

# WASM Execution
def execute_wasm(wasm_binary: bytes, inputs: List[str]) -> str:
    if wasm_binary in wasm_cache:
        module = wasm_cache[wasm_binary]
    else:
        module = Module(store, wasm_binary)
        wasm_cache[wasm_binary] = module
    
    instance = Instance(module)
    result = instance.exports.compute(*inputs)
    return str(result)

# Celery Tasks
@celery.task
def execute_python_code(code: str, inputs: List[str]) -> str:
    # Security note: In production, use a sandboxed environment
    locals_dict = {"inputs": inputs}
    exec(code, {}, locals_dict)
    return str(locals_dict.get("result"))

# API Endpoints
@app.on_event("startup")
async def startup_event():
    await connect_to_bootstrap_nodes()
    logger.info("MonadMesh backend started")

@app.post("/api/submit", response_model=TaskStatusResponse)
async def submit_function(submission: FunctionSubmission):
    task_id = str(uuid.uuid4())
    
    # Store task metadata
    task_data = {
        "status": "PENDING",
        "language": submission.language,
        "use_zk": str(submission.use_zk),
        "inputs": json.dumps(submission.inputs)
    }
    
    if submission.language == "wasm":
        try:
            wasm_binary = base64.b64decode(submission.code)
            task_data["code"] = submission.code  # Store base64
        except:
            raise HTTPException(400, "Invalid WASM binary")
    else:
        task_data["code"] = submission.code
    
    # Store in Redis
    redis_client.hset(f"task:{task_id}", mapping=task_data)
    
    # Register on blockchain
    tx_hash = contract.functions.registerTask(
        Web3.to_bytes(text=task_id),
        submission.use_zk
    ).transact({
        'from': w3.eth.default_account,
        'gas': 200000
    }).hex()
    
    redis_client.hset(f"task:{task_id}", "tx_hash", tx_hash)
    
    # Distribute to P2P network
    if submission.language == "wasm":
        for peer in p2p_node.peers():
            try:
                await p2p_node.send(
                    peer,
                    f"EXECUTE:{task_id}:{submission.code}"
                )
                redis_client.hset(
                    f"task:{task_id}", 
                    "executors", 
                    json.dumps(list(p2p_node.peers()))
            except Exception as e:
                logger.error(f"Failed to send to peer {peer}: {str(e)}")
    
    # Execute locally if no peers or Python task
    if submission.language == "python" or not p2p_node.peers():
        if submission.language == "wasm":
            result = execute_wasm(wasm_binary, submission.inputs)
        else:
            result = execute_python_code.delay(
                submission.code, 
                submission.inputs
            ).get()
        
        redis_client.hset(f"task:{task_id}", "result", result)
        redis_client.hset(f"task:{task_id}", "status", "COMPLETED")
        
        # Submit to blockchain
        contract.functions.submitResult(
            Web3.to_bytes(text=task_id),
            Web3.keccak(text=result),
            b''  # Empty ZK proof for now
        ).transact({
            'from': w3.eth.default_account,
            'gas': 200000
        })
    
    return TaskStatusResponse(
        task_id=task_id,
        status="PENDING",
        tx_hash=tx_hash,
        executors=list(p2p_node.peers())
    )

@app.websocket("/api/status/{task_id}")
async def websocket_status(websocket: WebSocket, task_id: str):
    await manager.connect(websocket)
    try:
        while True:
            data = redis_client.hgetall(f"task:{task_id}")
            if not data:
                await websocket.send_json({"error": "Task not found"})
                break
            
            response = {
                "status": data.get(b"status", b"UNKNOWN").decode(),
                "result": data.get(b"result", b"").decode(),
                "executors": json.loads(data.get(b"executors", b"[]"))
            }
            
            await websocket.send_json(response)
            await asyncio.sleep(2)  # Throttle updates
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        manager.disconnect(websocket)

@app.get("/api/task/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    data = redis_client.hgetall(f"task:{task_id}")
    if not data:
        raise HTTPException(404, "Task not found")
    
    return TaskStatusResponse(
        task_id=task_id,
        status=data.get(b"status", b"UNKNOWN").decode(),
        result=data.get(b"result", b"").decode(),
        tx_hash=data.get(b"tx_hash", b"").decode(),
        executors=json.loads(data.get(b"executors", b"[]"))
    )

@app.post("/api/upload/wasm")
async def upload_wasm(file: UploadFile):
    try:
        contents = await file.read()
        # Validate WASM
        Module(store, contents)
        return {"size": len(contents)}
    except Exception as e:
        raise HTTPException(400, f"Invalid WASM file: {str(e)}")

@app.get("/api/network/peers")
async def get_peers():
    return {"peers": list(p2p_node.peers())}

# Background Task for P2P Messages
async def handle_p2p_messages():
    while True:
        try:
            peer_id, message = await p2p_node.receive()
            if message.startswith("EXECUTE:"):
                _, task_id, code = message.split(":", 2)
                wasm_binary = base64.b64decode(code)
                inputs = json.loads(
                    redis_client.hget(f"task:{task_id}", "inputs") or "[]"
                )
                
                result = execute_wasm(wasm_binary, inputs)
                redis_client.hset(f"task:{task_id}", "result", result)
                redis_client.hset(f"task:{task_id}", "status", "COMPLETED")
                
                # Submit to blockchain
                contract.functions.submitResult(
                    Web3.to_bytes(text=task_id),
                    Web3.keccak(text=result),
                    b''  # Empty ZK proof for now
                ).transact({
                    'from': w3.eth.default_account,
                    'gas': 200000
                })
                
                await manager.broadcast(
                    json.dumps({"task_id": task_id, "status": "COMPLETED"})
                )
                
        except Exception as e:
            logger.error(f"P2P message handling error: {str(e)}")
            await asyncio.sleep(1)

# Start P2P handler on startup
@app.on_event("startup")
async def start_p2p_handler():
    asyncio.create_task(handle_p2p_messages())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)