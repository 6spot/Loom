SELECT
    work_id::text AS work_id,
    target_kind,
    target_owner,
    target_handler,
    target_agent_id::text AS target_agent_id,
    target_cognition,
    schema_revision,
    payload,
    effective_due_world_time,
    logical_schedule_order::text AS logical_schedule_order,
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
ORDER BY effective_due_world_time, logical_schedule_order
