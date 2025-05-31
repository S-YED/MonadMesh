# app.py
from fastapi import FastAPI, HTTPException, Depends, status, BackgroundTasks
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from typing import Optional, List, Dict
import os
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from pymongo import MongoClient
from bson import ObjectId
import json
import uuid
from web3 import Web3

# Initialize FastAPI
app = FastAPI()

# MongoDB Setup
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["monadmesh"]
users_collection = db["users"]
tasks_collection = db["tasks"]
functions_collection = db["functions"]
results_collection = db["results"]

# Web3 (Ethereum/Polygon connection)
WEB3_PROVIDER = os.getenv("WEB3_PROVIDER", "http://localhost:8545")
w3 = Web3(Web3.HTTPProvider(WEB3_PROVIDER))

# JWT Authentication Setup
SECRET_KEY = os.getenv("SECRET_KEY", "monadmesh-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Pydantic Models
class User(BaseModel):
    username: str
    email: str
    disabled: Optional[bool] = None

class UserInDB(User):
    hashed_password: str

class FunctionSubmission(BaseModel):
    code: str
    dependencies: Optional[List[str]] = []
    is_public: bool = False

class Task(BaseModel):
    function_id: str
    status: str  # "pending", "executing", "completed", "failed"
    submitted_by: str
    submitted_at: datetime
    completed_at: Optional[datetime] = None

class ExecutionResult(BaseModel):
    task_id: str
    output: Dict
    executed_by: Optional[str] = None
    execution_time: float

# Utility Functions
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def get_user(username: str):
    user_data = users_collection.find_one({"username": username})
    if user_data:
        return UserInDB(**user_data)

def authenticate_user(username: str, password: str):
    user = get_user(username)
    if not user or not verify_password(password, user.hashed_password):
        return False
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = get_user(username)
    if user is None:
        raise credentials_exception
    return user

# Background Task for P2P Execution Simulation
def simulate_p2p_execution(task_id: str, function_id: str):
    # In a real implementation, this would interact with the P2P network
    # Here we simulate execution after a delay
    import time
    time.sleep(5)  # Simulate execution time
    
    # Update task status to completed
    tasks_collection.update_one(
        {"_id": ObjectId(task_id)},
        {"$set": {"status": "completed", "completed_at": datetime.utcnow()}}
    )
    
    # Store a dummy result
    results_collection.insert_one({
        "task_id": task_id,
        "output": {"result": "simulated_execution_success"},
        "executed_by": "p2p_node_1",
        "execution_time": 5.0
    })

# API Endpoints

## Authentication Endpoints
@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/register")
async def register(username: str, email: str, password: str):
    if users_collection.find_one({"$or": [{"username": username}, {"email": email}]}):
        raise HTTPException(status_code=400, detail="Username or email already registered")
    
    hashed_password = get_password_hash(password)
    user_data = {
        "username": username,
        "email": email,
        "hashed_password": hashed_password,
        "disabled": False
    }
    users_collection.insert_one(user_data)
    return {"message": "User created successfully"}

## Function Management Endpoints
@app.post("/functions", status_code=status.HTTP_201_CREATED)
async def submit_function(
    function: FunctionSubmission,
    current_user: User = Depends(get_current_user),
    background_tasks: BackgroundTasks = None
):
    # Store the function in MongoDB
    function_data = {
        "code": function.code,
        "dependencies": function.dependencies,
        "is_public": function.is_public,
        "owner": current_user.username,
        "created_at": datetime.utcnow()
    }
    result = functions_collection.insert_one(function_data)
    function_id = str(result.inserted_id)
    
    # Create a new task
    task_data = {
        "function_id": function_id,
        "status": "pending",
        "submitted_by": current_user.username,
        "submitted_at": datetime.utcnow()
    }
    task_result = tasks_collection.insert_one(task_data)
    task_id = str(task_result.inserted_id)
    
    # Simulate P2P execution in background
    if background_tasks:
        background_tasks.add_task(simulate_p2p_execution, task_id, function_id)
    
    return {
        "message": "Function submitted successfully",
        "function_id": function_id,
        "task_id": task_id
    }

@app.get("/functions/{function_id}")
async def get_function(function_id: str, current_user: User = Depends(get_current_user)):
    function_data = functions_collection.find_one({"_id": ObjectId(function_id)})
    if not function_data:
        raise HTTPException(status_code=404, detail="Function not found")
    
    # Check if user has access
    if not function_data["is_public"] and function_data["owner"] != current_user.username:
        raise HTTPException(status_code=403, detail="Not authorized to access this function")
    
    return {
        "code": function_data["code"],
        "dependencies": function_data["dependencies"],
        "owner": function_data["owner"],
        "created_at": function_data["created_at"]
    }

## Task Management Endpoints
@app.get("/tasks/{task_id}")
async def get_task_status(task_id: str, current_user: User = Depends(get_current_user)):
    task_data = tasks_collection.find_one({"_id": ObjectId(task_id)})
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Verify task ownership
    if task_data["submitted_by"] != current_user.username:
        raise HTTPException(status_code=403, detail="Not authorized to access this task")
    
    return {
        "function_id": task_data["function_id"],
        "status": task_data["status"],
        "submitted_at": task_data["submitted_at"],
        "completed_at": task_data.get("completed_at")
    }

@app.get("/tasks")
async def list_user_tasks(current_user: User = Depends(get_current_user)):
    user_tasks = list(tasks_collection.find({"submitted_by": current_user.username}))
    return [{
        "task_id": str(task["_id"]),
        "function_id": task["function_id"],
        "status": task["status"],
        "submitted_at": task["submitted_at"]
    } for task in user_tasks]

## Result Endpoints
@app.get("/results/{task_id}")
async def get_task_result(task_id: str, current_user: User = Depends(get_current_user)):
    # Verify task ownership
    task_data = tasks_collection.find_one({"_id": ObjectId(task_id)})
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")
    if task_data["submitted_by"] != current_user.username:
        raise HTTPException(status_code=403, detail="Not authorized to access this task")
    
    # Get result
    result_data = results_collection.find_one({"task_id": task_id})
    if not result_data:
        raise HTTPException(status_code=404, detail="Result not available yet")
    
    return {
        "task_id": task_id,
        "output": result_data["output"],
        "executed_by": result_data.get("executed_by"),
        "execution_time": result_data.get("execution_time")
    }

# Health Check
@app.get("/health")
async def health_check():
    return {"status": "healthy", "database": "connected" if mongo_client else "disconnected"}