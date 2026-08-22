UPDATE loom_execution_session
SET status = $2, ended_at = $3, record = $4::jsonb
WHERE session_id = $1::uuid AND status = 'Started';
