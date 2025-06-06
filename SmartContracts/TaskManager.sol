contract TaskManager {
    enum TaskStatus { Pending, Executing, Completed, Failed }

    struct Task {
        bytes32 functionId;
        address submittedBy;
        TaskStatus status;
        uint256 reward;
        uint256 submittedAt;
        uint256 completedAt;
    }

    mapping(bytes32 => Task) public tasks;
    bytes32[] public pendingTasks;
    
    event TaskSubmitted(bytes32 taskId, bytes32 functionId);
    event TaskCompleted(bytes32 taskId, string resultIpfsHash);

    function submitTask(bytes32 _functionId) public payable returns (bytes32) {
        bytes32 taskId = keccak256(abi.encodePacked(_functionId, block.timestamp));
        tasks[taskId] = Task({
            functionId: _functionId,
            submittedBy: msg.sender,
            status: TaskStatus.Pending,
            reward: msg.value,
            submittedAt: block.timestamp,
            completedAt: 0
        });
        pendingTasks.push(taskId);
        emit TaskSubmitted(taskId, _functionId);
        return taskId;
    }

    function completeTask(bytes32 _taskId, string memory _resultIpfsHash) public {
        require(tasks[_taskId].status == TaskStatus.Pending, "Invalid task status");
        tasks[_taskId].status = TaskStatus.Completed;
        tasks[_taskId].completedAt = block.timestamp;
        payable(msg.sender).transfer(tasks[_taskId].reward);
        emit TaskCompleted(_taskId, _resultIpfsHash);
    }
}
