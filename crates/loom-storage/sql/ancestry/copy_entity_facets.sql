INSERT INTO loom_entity_facet
    (timeline_id, entity_id, facet_type, schema_revision, value)
SELECT $1::uuid, entity_id, facet_type, schema_revision, value
FROM loom_entity_facet
WHERE timeline_id = $2::uuid
