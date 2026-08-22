INSERT INTO loom_entity_facet
(timeline_id, entity_id, facet_type, schema_revision, value)
VALUES ($1::uuid, $2::uuid, $3, $4, $5)
ON CONFLICT (timeline_id, entity_id, facet_type) DO UPDATE
SET schema_revision = EXCLUDED.schema_revision,
    value = EXCLUDED.value;
