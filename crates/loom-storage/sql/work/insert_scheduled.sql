INSERT INTO loom_work
(timeline_id, work_id, target_kind, target_owner, target_handler, target_agent_id,
 target_cognition, schema_revision, payload, effective_due_world_time, logical_schedule_order,
 causal_event_id, origin_work_id, status, attempt_count, claim_generation, available_at,
 last_error, lease_claimed_until, lease_fence)
VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6::uuid, $7, $8, $9, $10, $11::numeric,
        $12::uuid, $13::uuid, 'pending', 0, 0, $14, NULL, NULL, NULL);
