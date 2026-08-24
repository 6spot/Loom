SELECT session_id::text AS session_id
FROM loom_execution_session_event
WHERE timeline_id = $1::uuid AND event_id = $2::uuid;
