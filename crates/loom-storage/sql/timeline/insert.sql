INSERT INTO loom_timeline
(timeline_id, world_id, head_event_seq, state_revision, world_time)
VALUES ($1::uuid, $2::uuid, 0, 0, $3);
