{
  "_id": ObjectId,
  "function_id": String,  // reference to functions._id
  "status": String,  // "pending", "executing", "completed", "failed"
  "submitted_by": String,  // username
  "submitted_at": DateTime,
  "completed_at": DateTime (optional)
}