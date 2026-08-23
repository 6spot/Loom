SELECT
    world_id::text,
    timeline_id::text,
    index_id,
    source_kind,
    source_type_id,
    source_schema_revision::text,
    schema_revision::text,
    projection_revision::text,
    model_revision,
    dimensions,
    metric
FROM loom_semantic_projection_index
WHERE world_id = $1::uuid
  AND timeline_id = $2::uuid
  AND index_id = $3
FOR UPDATE
