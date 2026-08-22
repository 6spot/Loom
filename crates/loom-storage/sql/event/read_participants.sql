SELECT
    entity_id::text AS entity_id,
    role
FROM loom_event_participant
WHERE timeline_id = $1::uuid
  AND event_id = $2::uuid
ORDER BY participant_order
