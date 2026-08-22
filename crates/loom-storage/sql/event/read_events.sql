SELECT
    event_id::text AS event_id,
    event_seq::text AS event_seq,
    event_type,
    schema_revision,
    occurred_at,
    payload,
    effects
FROM loom_event
WHERE timeline_id = $1::uuid
ORDER BY event_seq
