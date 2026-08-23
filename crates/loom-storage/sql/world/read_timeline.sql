SELECT
    world_id::text AS world_id,
    head_event_seq::text AS head_event_seq,
    state_revision::text AS state_revision,
    world_time,
    chronology_budget_world_time,
    chronology_budget_consumed::text AS chronology_budget_consumed,
    parent_timeline_id::text AS parent_timeline_id,
    fork_parent_head_event_seq::text AS fork_parent_head_event_seq,
    fork_parent_state_revision::text AS fork_parent_state_revision,
    fork_parent_event_timeline_id::text AS fork_parent_event_timeline_id,
    fork_parent_event_id::text AS fork_parent_event_id
FROM loom_timeline
WHERE timeline_id = $1::uuid
