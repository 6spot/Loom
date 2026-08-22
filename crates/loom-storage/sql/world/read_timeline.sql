SELECT
    world_id::text AS world_id,
    head_event_seq::text AS head_event_seq,
    state_revision::text AS state_revision,
    world_time
FROM loom_timeline
WHERE timeline_id = $1::uuid
