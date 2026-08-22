SELECT status, lease_claimed_until, lease_fence::text AS lease_fence
FROM loom_work
WHERE timeline_id = $1::uuid AND work_id = $2::uuid
FOR UPDATE;
