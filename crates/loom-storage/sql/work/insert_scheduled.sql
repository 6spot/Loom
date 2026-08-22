INSERT INTO loom_work
(timeline_id, work_id, handler, schema_revision, payload, due_world_time, causal_event_id,
 origin_work_id, status, attempt_count, claim_generation, available_at, last_error,
 lease_claimed_until, lease_fence)
VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7::uuid, $8::uuid, 'pending', 0, 0, $9,
        NULL, NULL, NULL);
