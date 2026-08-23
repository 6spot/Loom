UPDATE loom_ingress
SET status = $2,
    available_at = $3,
    lease_claimed_until = NULL,
    lease_fence = NULL,
    last_error_code = $4,
    last_error_message = $5,
    record = $6::jsonb
WHERE ingress_id = $1
  AND status = 'processing'
  AND lease_fence = $7::numeric
  AND lease_claimed_until = $8;
