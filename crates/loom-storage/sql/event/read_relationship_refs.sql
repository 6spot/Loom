SELECT
    relationship_id::text AS relationship_id,
    role
FROM loom_event_relationship_ref
WHERE timeline_id = $1::uuid
  AND event_id = $2::uuid
ORDER BY reference_order
