{
  "_id": ObjectId,
  "task_id": String,  // reference to tasks._id
  "output": Object,  // JSON result
  "executed_by": String (optional),  // P2P node ID
  "execution_time": Float (optional)  // in seconds
}