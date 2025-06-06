pragma solidity ^0.8.0;

contract FunctionRegistry {
    struct Function {
        address owner;
        string ipfsHash;
        string[] dependencies;
        bool isPublic;
        uint256 createdAt;
    }

    mapping(bytes32 => Function) public functions;
    mapping(address => bytes32[]) public userFunctions;
    
    event FunctionRegistered(bytes32 functionId, address owner);

    function registerFunction(
        string memory _ipfsHash,
        string[] memory _dependencies,
        bool _isPublic
    ) public returns (bytes32) {
        bytes32 functionId = keccak256(abi.encodePacked(_ipfsHash, block.timestamp));
        functions[functionId] = Function({
            owner: msg.sender,
            ipfsHash: _ipfsHash,
            dependencies: _dependencies,
            isPublic: _isPublic,
            createdAt: block.timestamp
        });
        userFunctions[msg.sender].push(functionId);
        emit FunctionRegistered(functionId, msg.sender);
        return functionId;
    }

    function getFunction(bytes32 _functionId) public view returns (Function memory) {
        return functions[_functionId];
    }
}
