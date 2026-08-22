UPDATE loom_work
SET status = 'cancelled', lease_claimed_until = NULL, lease_fence = NULL
WHERE timeline_id = $1::uuid AND work_id = $2::uuid;
