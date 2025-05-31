# app.py
from fastapi import FastAPI, HTTPException, Depends, status, Request, BackgroundTasks
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
import os
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from pymongo import MongoClient
from bson import ObjectId
import json
import uuid
from web3 import Web3, HTTPProvider
from web3.middleware import geth_poa_middleware
from eth_account import Account
from eth_account.messages import encode_defunct
import ipfshttpclient
import secrets

# Initialize FastAPI
app = FastAPI(title="MonadMesh Wallet API")

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database Setup
mongo_client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = mongo_client["monadmesh"]
users_collection = db["users"]
wallets_collection = db["wallets"]
sessions_collection = db["sessions"]
transactions_collection = db["transactions"]

# Web3 Configuration
w3 = Web3(HTTPProvider(os.getenv("WEB3_PROVIDER", "http://localhost:8545")))
w3.middleware_onion.inject(geth_poa_middleware, layer=0)

# IPFS Setup
ipfs_client = ipfshttpclient.connect()

# Security Configuration
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

# Contract Addresses (Replace with actual addresses)
CONTRACT_ADDRESSES = {
    "function_registry": "0x123...",
    "task_orchestrator": "0x456...",
    "proof_verifier": "0x789..."
}

# Load Contract ABIs (Simplified)
with open("abis/FunctionRegistry.json") as f:
    FUNCTION_REGISTRY_ABI = json.load(f)

with open("abis/TaskOrchestrator.json") as f:
    TASK_ORCHESTRATOR_ABI = json.load(f)

# Models
class User(BaseModel):
    username: str
    email: str
    disabled: bool = False

class UserInDB(User):
    hashed_password: str

class Wallet(BaseModel):
    address: str
    user_id: str
    nickname: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class WalletCreate(BaseModel):
    nickname: Optional[str] = None
    password: str  # For encrypting the private key

class Transaction(BaseModel):
    tx_hash: str
    from_address: str
    to_address: str
    value: float
    status: str  # "pending", "confirmed", "failed"
    created_at: datetime = Field(default_factory=datetime.utcnow)

class SignedMessage(BaseModel):
    message: str
    signature: str
    address: str

# Utility Functions
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserInDB:
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
    
    user = users_collection.find_one({"username": username})
    if user is None:
        raise credentials_exception
    return UserInDB(**user)

def create_wallet(password: str) -> Dict:
    """Create a new Ethereum wallet with encrypted private key"""
    acct = Account.create()
    encrypted_key = Account.encrypt(acct.key.hex(), password)
    return {
        "address": acct.address,
        "private_key": encrypted_key,
        "balance": 0.0
    }

def sign_message(private_key: str, message: str) -> str:
    """Sign a message with the wallet's private key"""
    message_hash = encode_defunct(text=message)
    signed_message = Account.sign_message(message_hash, private_key)
    return signed_message.signature.hex()

# API Endpoints

## Authentication Endpoints
@app.post("/auth/register", response_model=User)
async def register_user(username: str, email: str, password: str):
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
    return User(**user_data)

@app.post("/auth/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = users_collection.find_one({"username": form_data.username})
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"]}, expires_delta=access_token_expires
    )
    
    # Create session
    session_id = str(uuid.uuid4())
    sessions_collection.insert_one({
        "session_id": session_id,
        "user_id": str(user["_id"]),
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + access_token_expires
    })
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "session_id": session_id
    }

## Wallet Management Endpoints
@app.post("/wallets/create", response_model=Wallet)
async def create_wallet_endpoint(
    wallet_data: WalletCreate,
    current_user: UserInDB = Depends(get_current_user)
):
    """Create a new Ethereum wallet for the user"""
    wallet = create_wallet(wallet_data.password)
    
    wallet_doc = {
        "address": wallet["address"],
        "user_id": str(current_user.id),
        "nickname": wallet_data.nickname,
        "encrypted_private_key": wallet["private_key"],
        "created_at": datetime.utcnow()
    }
    
    wallets_collection.insert_one(wallet_doc)
    return Wallet(**wallet_doc)

@app.get("/wallets", response_model=List[Wallet])
async def get_user_wallets(current_user: UserInDB = Depends(get_current_user)):
    """Get all wallets belonging to the current user"""
    wallets = list(wallets_collection.find({"user_id": str(current_user.id)}))
    return [Wallet(**wallet) for wallet in wallets]

@app.post("/wallets/{wallet_address}/sign")
async def sign_message_endpoint(
    wallet_address: str,
    message: str,
    password: str,
    current_user: UserInDB = Depends(get_current_user)
):
    """Sign a message with the specified wallet"""
    wallet = wallets_collection.find_one({
        "address": wallet_address,
        "user_id": str(current_user.id)
    })
    
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    try:
        # Decrypt private key
        private_key = Account.decrypt(wallet["encrypted_private_key"], password)
        signature = sign_message(private_key, message)
        return {"signature": signature}
    except ValueError as e:
        raise HTTPException(status_code=401, detail="Invalid password")

## Transaction Endpoints
@app.post("/transactions/send")
async def send_transaction(
    from_address: str,
    to_address: str,
    value: float,
    data: Optional[str] = None,
    password: str = None,
    current_user: UserInDB = Depends(get_current_user)
):
    """Send a transaction from the specified wallet"""
    wallet = wallets_collection.find_one({
        "address": from_address,
        "user_id": str(current_user.id)
    })
    
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    try:
        # Decrypt private key
        private_key = Account.decrypt(wallet["encrypted_private_key"], password)
        
        # Build transaction
        tx = {
            'to': to_address,
            'value': w3.toWei(value, 'ether'),
            'gas': 2000000,
            'gasPrice': w3.toWei('50', 'gwei'),
            'nonce': w3.eth.getTransactionCount(from_address),
            'chainId': 1337  # Update for mainnet
        }
        
        if data:
            tx['data'] = data
        
        # Sign and send
        signed_tx = Account.signTransaction(tx, private_key)
        tx_hash = w3.eth.sendRawTransaction(signed_tx.rawTransaction)
        
        # Store transaction
        tx_doc = {
            "tx_hash": tx_hash.hex(),
            "from_address": from_address,
            "to_address": to_address,
            "value": value,
            "status": "pending",
            "user_id": str(current_user.id),
            "created_at": datetime.utcnow()
        }
        transactions_collection.insert_one(tx_doc)
        
        return {"tx_hash": tx_hash.hex()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

## Smart Contract Interaction Endpoints
@app.post("/contracts/function_registry/register")
async def register_function(
    wallet_address: str,
    ipfs_hash: str,
    dependencies: List[str],
    is_public: bool,
    password: str,
    current_user: UserInDB = Depends(get_current_user)
):
    """Register a new function in the FunctionRegistry contract"""
    wallet = wallets_collection.find_one({
        "address": wallet_address,
        "user_id": str(current_user.id)
    })
    
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    try:
        # Get contract instance
        contract = w3.eth.contract(
            address=CONTRACT_ADDRESSES["function_registry"],
            abi=FUNCTION_REGISTRY_ABI
        )
        
        # Prepare transaction
        tx = contract.functions.registerFunction(
            ipfs_hash,
            [w3.keccak(text=d) for d in dependencies],
            is_public
        ).buildTransaction({
            'from': wallet_address,
            'nonce': w3.eth.getTransactionCount(wallet_address),
            'gas': 500000,
            'gasPrice': w3.toWei('50', 'gwei')
        })
        
        # Sign and send
        private_key = Account.decrypt(wallet["encrypted_private_key"], password)
        signed_tx = Account.signTransaction(tx, private_key)
        tx_hash = w3.eth.sendRawTransaction(signed_tx.rawTransaction)
        
        return {"tx_hash": tx_hash.hex()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/transactions/{tx_hash}")
async def get_transaction_status(
    tx_hash: str,
    current_user: UserInDB = Depends(get_current_user)
):
    """Check the status of a transaction"""
    tx = transactions_collection.find_one({
        "tx_hash": tx_hash,
        "user_id": str(current_user.id)
    })
    
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # Check blockchain status
    try:
        receipt = w3.eth.getTransactionReceipt(tx_hash)
        status = "confirmed" if receipt and receipt.status == 1 else "failed"
        
        # Update in DB
        transactions_collection.update_one(
            {"tx_hash": tx_hash},
            {"$set": {"status": status}}
        )
        
        return {"status": status}
    except:
        return {"status": "pending"}

# Health Check
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "web3_connected": w3.isConnected(),
        "mongo_connected": mongo_client.server_info() is not None,
        "ipfs_connected": ipfs_client is not None
    }
