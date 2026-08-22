UPDATE loom_work
SET attempt_count = $3,
    claim_generation = $4::numeric,
    lease_claimed_until = $5,
    lease_fence = $4::numeric
WHERE timeline_id = $1::uuid
  AND work_id = $2::uuid
