UPDATE loom_work
SET status = 'completed', lease_claimed_until = NULL, lease_fence = NULL, last_error = NULL
WHERE timeline_id = $1::uuid AND work_id = $2::uuid;
