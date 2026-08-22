SELECT
    relationship_id::text AS relationship_id,
    relationship_type,
    active
FROM loom_relationship
WHERE timeline_id = $1::uuid
ORDER BY relationship_id
