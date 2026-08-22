UPDATE loom_timeline
SET head_event_seq = $2::numeric, state_revision = $3::numeric
WHERE timeline_id = $1::uuid;
