UPDATE loom_ingress
SET status = $2,
    lease_claimed_until = NULL,
    lease_fence = NULL,
    last_error_code = NULL,
    last_error_message = NULL,
    completed_session_id = $3::uuid,
    completed_event_refs = $4::jsonb,
    completion = $5::jsonb,
    completed_at = $6,
    record = $7::jsonb
WHERE ingress_id = $1
  AND status = 'processing'
  AND lease_fence = $8::numeric
  AND lease_claimed_until = $9;
