SELECT
    entity_id::text AS owner_id,
    facet_type,
    schema_revision,
    value
FROM loom_entity_facet
WHERE timeline_id = $1::uuid
ORDER BY entity_id, facet_type
