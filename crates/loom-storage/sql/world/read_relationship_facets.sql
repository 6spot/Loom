SELECT
    relationship_id::text AS owner_id,
    facet_type,
    schema_revision,
    value
FROM loom_relationship_facet
WHERE timeline_id = $1::uuid
ORDER BY relationship_id, facet_type
