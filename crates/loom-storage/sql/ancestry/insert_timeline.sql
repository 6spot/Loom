INSERT INTO loom_timeline (
    timeline_id, world_id, head_event_seq, state_revision, world_time,
    chronology_budget_world_time, chronology_budget_consumed,
    parent_timeline_id, fork_parent_head_event_seq, fork_parent_state_revision,
    fork_parent_event_id
)
VALUES (
    $1::uuid, $2::uuid, $3::numeric, $4::numeric, $5,
    $6, $7::numeric, $8::uuid, $9::numeric, $10::numeric, $11::uuid
)
