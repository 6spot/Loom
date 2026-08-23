UPDATE loom_ingress
SET status = $2,
    attempt_count = $3,
    claim_fence = $4::numeric,
    lease_claimed_until = $5,
    lease_fence = $4::numeric,
    record = $6::jsonb
WHERE ingress_id = $1
  AND status IN ('accepted', 'retryable', 'processing');
