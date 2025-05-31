from flask import Flask, jsonify, request
from flask_cors import CORS
from web3 import Web3
import pymongo
import os
from dotenv import load_dotenv
import json

load_dotenv()

app = Flask(__name__)
CORS(app)

# Initialize Web3
w3 = Web3(Web3.HTTPProvider(os.getenv('WEB3_PROVIDER_URL')))
contract_address = os.getenv('CONTRACT_ADDRESS')
with open('MonadMesh.json') as f:
    contract_abi = json.load(f)['abi']
contract = w3.eth.contract(address=contract_address, abi=contract_abi)

# Initialize MongoDB
mongo_client = pymongo.MongoClient(os.getenv('MONGODB_URI'))
db = mongo_client['monadmesh']

# Auth endpoints
@app.route('/api/auth/nonce', methods=['GET'])
def get_nonce():
    address = request.args.get('address')
    if not address or not w3.is_address(address):
        return jsonify({'error': 'Invalid address'}), 400
    
    nonce = os.urandom(32).hex()
    db.users.update_one(
        {'address': address.lower()},
        {'$set': {'nonce': nonce}},
        upsert=True
    )
    return jsonify({'nonce': nonce})

@app.route('/api/auth/verify', methods=['POST'])
def verify_signature():
    data = request.json
    address = data.get('address')
    signature = data.get('signature')
    
    user = db.users.find_one({'address': address.lower()})
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    message = f"MonadMesh Auth: {user['nonce']}"
    try:
        recovered_address = w3.eth.account.recover_message(
            w3.eth.account.messages.encode_defunct(text=message),
            signature=signature
        )
    except:
        return jsonify({'error': 'Invalid signature'}), 400
    
    if recovered_address.lower() != address.lower():
        return jsonify({'error': 'Address mismatch'}), 401
    
    # Generate session token (JWT would be better in production)
    session_token = os.urandom(32).hex()
    db.users.update_one(
        {'address': address.lower()},
        {'$set': {'session_token': session_token}}
    )
    
    return jsonify({
        'session_token': session_token,
        'address': address
    })

# Function management endpoints
@app.route('/api/functions', methods=['POST'])
def submit_function():
    # Verify session
    session_token = request.headers.get('Authorization')
    if not session_token:
        return jsonify({'error': 'Unauthorized'}), 401
    
    user = db.users.find_one({'session_token': session_token})
    if not user:
        return jsonify({'error': 'Invalid session'}), 401
    
    # Get function data
    function_data = request.json
    if not all(k in function_data for k in ['code', 'dependencies', 'environment']):
        return jsonify({'error': 'Missing required fields'}), 400
    
    # Store in MongoDB
    function_id = db.functions.insert_one({
        'owner': user['address'],
        'code': function_data['code'],
        'dependencies': function_data['dependencies'],
        'environment': function_data['environment'],
        'status': 'pending',
        'created_at': datetime.datetime.utcnow()
    }).inserted_id
    
    # Trigger smart contract
    tx_hash = contract.functions.registerFunction(
        str(function_id),
        user['address']
    ).transact({
        'from': user['address'],
        'gas': 500000
    })
    
    return jsonify({
        'function_id': str(function_id),
        'tx_hash': tx_hash.hex()
    })

@app.route('/api/functions/<function_id>', methods=['GET'])
def get_function(function_id):
    function = db.functions.find_one({'_id': function_id})
    if not function:
        return jsonify({'error': 'Function not found'}), 404
    
    return jsonify({
        'id': str(function['_id']),
        'owner': function['owner'],
        'code': function['code'],
        'status': function['status'],
        'created_at': function['created_at'].isoformat()
    })

# Execution endpoints
@app.route('/api/execute', methods=['POST'])
def execute_function():
    session_token = request.headers.get('Authorization')
    if not session_token:
        return jsonify({'error': 'Unauthorized'}), 401
    
    user = db.users.find_one({'session_token': session_token})
    if not user:
        return jsonify({'error': 'Invalid session'}), 401
    
    data = request.json
    if not all(k in data for k in ['function_id', 'params']):
        return jsonify({'error': 'Missing required fields'}), 400
    
    # Create execution record
    execution_id = db.executions.insert_one({
        'function_id': data['function_id'],
        'params': data['params'],
        'caller': user['address'],
        'status': 'queued',
        'created_at': datetime.datetime.utcnow()
    }).inserted_id
    
    # Trigger smart contract
    tx_hash = contract.functions.requestExecution(
        str(execution_id),
        data['function_id'],
        user['address']
    ).transact({
        'from': user['address'],
        'gas': 500000
    })
    
    return jsonify({
        'execution_id': str(execution_id),
        'tx_hash': tx_hash.hex()
    })

# P2P Network endpoints
@app.route('/api/network/nodes', methods=['GET'])
def get_network_nodes():
    nodes = list(db.nodes.find({'status': 'active'}))
    return jsonify([{
        'node_id': str(node['_id']),
        'address': node['address'],
        'last_ping': node['last_ping'].isoformat(),
        'capabilities': node['capabilities']
    } for node in nodes])

@app.route('/api/network/register', methods=['POST'])
def register_node():
    data = request.json
    if not all(k in data for k in ['address', 'capabilities']):
        return jsonify({'error': 'Missing required fields'}), 400
    
    node_id = db.nodes.insert_one({
        'address': data['address'],
        'capabilities': data['capabilities'],
        'status': 'active',
        'last_ping': datetime.datetime.utcnow()
    }).inserted_id
    
    return jsonify({'node_id': str(node_id)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
