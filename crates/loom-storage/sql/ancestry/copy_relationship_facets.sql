INSERT INTO loom_relationship_facet
    (timeline_id, relationship_id, facet_type, schema_revision, value)
SELECT $1::uuid, relationship_id, facet_type, schema_revision, value
FROM loom_relationship_facet
WHERE timeline_id = $2::uuid
