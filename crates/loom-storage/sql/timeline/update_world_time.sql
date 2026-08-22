UPDATE loom_timeline
SET state_revision = $2::numeric,
    world_time = $3
WHERE timeline_id = $1::uuid;
