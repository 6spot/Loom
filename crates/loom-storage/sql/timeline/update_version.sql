UPDATE loom_timeline
SET head_event_seq = $2::numeric,
    state_revision = $3::numeric,
    chronology_budget_world_time = $4,
    chronology_budget_consumed = $5::numeric,
    logical_schedule_order = $6::numeric
WHERE timeline_id = $1::uuid;
