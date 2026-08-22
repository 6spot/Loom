INSERT INTO loom_execution_session
(session_id, world_id, timeline_id, origin, status, started_at, ended_at, record)
VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, NULL, $7::jsonb);
