INSERT INTO loom_relationship_facet
(timeline_id, relationship_id, facet_type, schema_revision, value)
VALUES ($1::uuid, $2::uuid, $3, $4, $5)
ON CONFLICT (timeline_id, relationship_id, facet_type) DO UPDATE
SET schema_revision = EXCLUDED.schema_revision,
    value = EXCLUDED.value;
