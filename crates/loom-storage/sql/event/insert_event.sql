INSERT INTO loom_event
(timeline_id, event_id, event_seq, event_type, schema_revision, occurred_at, payload, effects)
VALUES ($1::uuid, $2::uuid, $3::numeric, $4, $5, $6, $7, $8);
