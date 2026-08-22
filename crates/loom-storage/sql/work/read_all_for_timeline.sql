SELECT
    work_id::text AS work_id,
    handler,
    schema_revision,
    payload,
    due_world_time,
    causal_event_id::text AS causal_event_id,
    origin_work_id::text AS origin_work_id,
    status,
    attempt_count,
    claim_generation::text AS claim_generation,
    available_at,
    last_error,
    lease_claimed_until,
    lease_fence::text AS lease_fence
FROM loom_work
WHERE timeline_id = $1::uuid
ORDER BY work_id
