SELECT record
FROM loom_execution_session
WHERE session_id = $1::uuid;
