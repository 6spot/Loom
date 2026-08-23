UPDATE loom_semantic_projection_index
SET source_kind = $4,
    source_type_id = $5,
    source_schema_revision = $6,
    schema_revision = $7,
    projection_revision = $8::numeric,
    model_revision = $9,
    dimensions = $10,
    metric = $11
WHERE world_id = $1::uuid
  AND timeline_id = $2::uuid
  AND index_id = $3
