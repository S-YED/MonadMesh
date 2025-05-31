import os
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, g
from flask_cors import CORS
from web3 import Web3
from web3.auto import w3
from eth_account.messages import encode_defunct
import jwt
import pymongo
from dotenv import load_dotenv
import json
from functools import wraps

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Configuration
app.config['SECRET_KEY'] = os.getenv('JWT_SECRET', 'monadmesh-super-secret')
app.config['JWT_EXPIRATION_DELTA'] = timedelta(hours=24)

# Web3 Initialization
web3 = Web3(Web3.HTTPProvider(os.getenv('WEB3_PROVIDER_URL', 'https://mainnet.infura.io/v3/YOUR_INFURA_KEY')))
chain_id = int(os.getenv('CHAIN_ID', 1))  # Default to Ethereum Mainnet

# Smart Contract
with open('MonadMesh.json') as f:
    contract_abi = json.load(f)['abi']
contract_address = os.getenv('CONTRACT_ADDRESS')
contract = web3.eth.contract(address=contract_address, abi=contract_abi)

# MongoDB Initialization
mongo_client = pymongo.MongoClient(os.getenv('MONGODB_URI', 'mongodb://localhost:27017'))
db = mongo_client['monadmesh_prod']

# Authentication Decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({'error': 'Authorization header missing'}), 401
        
        try:
            token = auth_header.split(' ')[1]
            payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            g.current_user = payload['sub']
            g.wallet_address = payload['wallet_address']
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        except (jwt.InvalidTokenError, IndexError, KeyError) as e:
            return jsonify({'error': 'Invalid token', 'details': str(e)}), 401
        
        return f(*args, **kwargs)
    return decorated_function

# Auth Endpoints
@app.route('/api/auth/nonce', methods=['GET'])
def get_nonce():
    wallet_address = request.args.get('wallet_address')
    
    if not wallet_address:
        return jsonify({'error': 'wallet_address parameter is required'}), 400
    
    try:
        # Validate Ethereum address
        if not web3.is_address(wallet_address):
            return jsonify({'error': 'Invalid Ethereum address'}), 400
        
        # Normalize address
        wallet_address = web3.to_checksum_address(wallet_address)
        
        # Generate a secure random nonce
        nonce = os.urandom(32).hex()
        
        # Store nonce in database with expiration (5 minutes)
        db.users.update_one(
            {'wallet_address': wallet_address},
            {'$set': {
                'nonce': nonce,
                'nonce_expires_at': datetime.utcnow() + timedelta(minutes=5)
            }},
            upsert=True
        )
        
        return jsonify({
            'nonce': nonce,
            'wallet_address': wallet_address,
            'chain_id': chain_id,
            'message': f"MonadMesh Auth: {nonce}",
            'expires_in': 300  # 5 minutes in seconds
        })
    
    except Exception as e:
        return jsonify({'error': 'Server error', 'details': str(e)}), 500

@app.route('/api/auth/verify', methods=['POST'])
def verify_signature():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
        
        required_fields = ['wallet_address', 'signature']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400
        
        wallet_address = data['wallet_address']
        signature = data['signature']
        
        # Validate Ethereum address
        if not web3.is_address(wallet_address):
            return jsonify({'error': 'Invalid Ethereum address'}), 400
        
        wallet_address = web3.to_checksum_address(wallet_address)
        
        # Retrieve nonce from database
        user = db.users.find_one({'wallet_address': wallet_address})
        if not user or 'nonce' not in user:
            return jsonify({'error': 'Nonce not found. Request a new nonce first.'}), 404
        
        # Check nonce expiration
        if user.get('nonce_expires_at', datetime.min) < datetime.utcnow():
            return jsonify({'error': 'Nonce expired. Request a new one.'}), 401
        
        # Prepare the expected message
        message = f"MonadMesh Auth: {user['nonce']}"
        
        # Verify the signature
        try:
            message_hash = encode_defunct(text=message)
            signer = web3.eth.account.recover_message(message_hash, signature=signature)
            signer = web3.to_checksum_address(signer)
        except Exception as e:
            return jsonify({'error': 'Signature verification failed', 'details': str(e)}), 401
        
        if signer != wallet_address:
            return jsonify({'error': 'Signature does not match wallet address'}), 401
        
        # Generate JWT token
        token_payload = {
            'sub': str(user.get('_id', '')),
            'wallet_address': wallet_address,
            'exp': datetime.utcnow() + app.config['JWT_EXPIRATION_DELTA']
        }
        
        token = jwt.encode(token_payload, app.config['SECRET_KEY'], algorithm='HS256')
        
        # Update user record
        db.users.update_one(
            {'wallet_address': wallet_address},
            {'$set': {
                'last_login': datetime.utcnow(),
                'jwt_token': token
            }}
        )
        
        return jsonify({
            'token': token,
            'wallet_address': wallet_address,
            'expires_in': app.config['JWT_EXPIRATION_DELTA'].total_seconds()
        })
    
    except Exception as e:
        return jsonify({'error': 'Server error', 'details': str(e)}), 500

# User Profile Endpoint
@app.route('/api/auth/profile', methods=['GET'])
@login_required
def get_profile():
    try:
        user = db.users.find_one(
            {'wallet_address': g.wallet_address},
            {'_id': 0, 'nonce': 0, 'nonce_expires_at': 0}
        )
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Get user's functions and executions count
        functions_count = db.functions.count_documents({'owner': g.wallet_address})
        executions_count = db.executions.count_documents({'caller': g.wallet_address})
        
        profile = {
            'wallet_address': user['wallet_address'],
            'registered_at': user.get('created_at', '').isoformat(),
            'last_login': user.get('last_login', '').isoformat(),
            'stats': {
                'functions': functions_count,
                'executions': executions_count
            }
        }
        
        return jsonify(profile)
    
    except Exception as e:
        return jsonify({'error': 'Server error', 'details': str(e)}), 500

# Wallet Linking Endpoint (for additional security)
@app.route('/api/auth/link-wallet', methods=['POST'])
@login_required
def link_wallet():
    try:
        data = request.get_json()
        if not data or 'signature' not in data or 'new_wallet_address' not in data:
            return jsonify({'error': 'Signature and new_wallet_address are required'}), 400
        
        new_wallet_address = data['new_wallet_address']
        signature = data['signature']
        
        if not web3.is_address(new_wallet_address):
            return jsonify({'error': 'Invalid Ethereum address'}), 400
        
        new_wallet_address = web3.to_checksum_address(new_wallet_address)
        
        # Verify the new wallet owns the signature of the main wallet
        message = f"Link wallet {new_wallet_address} to {g.wallet_address}"
        message_hash = encode_defunct(text=message)
        
        try:
            signer = web3.eth.account.recover_message(message_hash, signature=signature)
            signer = web3.to_checksum_address(signer)
        except Exception as e:
            return jsonify({'error': 'Signature verification failed', 'details': str(e)}), 401
        
        if signer != new_wallet_address:
            return jsonify({'error': 'Signature does not match new wallet address'}), 401
        
        # Link the wallets
        db.users.update_one(
            {'wallet_address': g.wallet_address},
            {'$addToSet': {'linked_wallets': new_wallet_address}}
        )
        
        return jsonify({
            'message': 'Wallet linked successfully',
            'main_wallet': g.wallet_address,
            'linked_wallet': new_wallet_address
        })
    
    except Exception as e:
        return jsonify({'error': 'Server error', 'details': str(e)}), 500

# Function Management Endpoints (with auth)
@app.route('/api/functions', methods=['GET'])
@login_required
def get_user_functions():
    try:
        functions = list(db.functions.find(
            {'owner': g.wallet_address},
            {'_id': 1, 'name': 1, 'description': 1, 'status': 1, 'created_at': 1}
        ).sort('created_at', -1))
        
        return jsonify([{
            'id': str(func['_id']),
            'name': func.get('name', 'Unnamed Function'),
            'description': func.get('description', ''),
            'status': func.get('status', 'active'),
            'created_at': func.get('created_at', '').isoformat()
        } for func in functions])
    
    except Exception as e:
        return jsonify({'error': 'Server error', 'details': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true')
