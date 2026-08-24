UPDATE loom_execution_session
SET record = $2::jsonb
WHERE session_id = $1::uuid AND status = 'Started' AND ended_at IS NULL;
