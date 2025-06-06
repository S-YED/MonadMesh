contract NodeRegistry {
    struct Node {
        address nodeAddress;
        string[] capabilities;
        uint256 stakeAmount;
        bool isActive;
    }

    mapping(address => Node) public nodes;
    address[] public activeNodes;
    
    event NodeRegistered(address nodeAddress);
    event NodeStaked(address nodeAddress, uint256 amount);

    function registerNode(string[] memory _capabilities) public {
        nodes[msg.sender] = Node({
            nodeAddress: msg.sender,
            capabilities: _capabilities,
            stakeAmount: 0,
            isActive: true
        });
        activeNodes.push(msg.sender);
        emit NodeRegistered(msg.sender);
    }

    function stake() public payable {
        nodes[msg.sender].stakeAmount += msg.value;
        emit NodeStaked(msg.sender, msg.value);
    }
}
