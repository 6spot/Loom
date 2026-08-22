UPDATE loom_timeline
SET state_revision = $2::numeric,
    world_time = $3,
    chronology_budget_world_time = $3,
    chronology_budget_consumed = 0
WHERE timeline_id = $1::uuid;
