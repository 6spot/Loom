UPDATE loom_work
SET available_at = $3,
    last_error = $4,
    lease_claimed_until = NULL,
    lease_fence = NULL
WHERE timeline_id = $1::uuid
  AND work_id = $2::uuid
