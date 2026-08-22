SELECT
    entity_id::text AS entity_id,
    role
FROM loom_relationship_participant
WHERE timeline_id = $1::uuid
  AND relationship_id = $2::uuid
ORDER BY participant_order
