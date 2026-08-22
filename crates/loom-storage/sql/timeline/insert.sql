INSERT INTO loom_timeline
(timeline_id, world_id, head_event_seq, state_revision, world_time,
 chronology_budget_world_time, chronology_budget_consumed)
VALUES ($1::uuid, $2::uuid, 0, 0, $3, $3, 0);
