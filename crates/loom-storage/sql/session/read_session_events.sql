SELECT timeline_id::text AS timeline_id, event_id::text AS event_id
FROM loom_execution_session_event
WHERE session_id = $1::uuid
ORDER BY event_seq ASC, timeline_id ASC, event_id ASC;
