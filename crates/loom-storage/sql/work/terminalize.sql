UPDATE loom_work
SET status = $3,
    lease_claimed_until = NULL,
    lease_fence = NULL,
    last_error = COALESCE($4, last_error)
WHERE timeline_id = $1::uuid
  AND work_id = $2::uuid
  AND status = 'pending';
