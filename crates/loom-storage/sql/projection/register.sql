INSERT INTO loom_semantic_projection_index (
    world_id,
    timeline_id,
    index_id,
    source_kind,
    source_type_id,
    source_schema_revision,
    schema_revision,
    projection_revision,
    model_revision,
    dimensions,
    metric
)
VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8::numeric, $9, $10, $11)
ON CONFLICT (world_id, timeline_id, index_id) DO NOTHING
