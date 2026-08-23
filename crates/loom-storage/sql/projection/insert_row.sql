INSERT INTO loom_semantic_projection_row (
    world_id,
    timeline_id,
    index_id,
    source_timeline_id,
    source_event_id,
    source_hash,
    source_head_event_seq,
    source_state_revision,
    projection_revision,
    model_revision,
    vector_data,
    dimensions
)
VALUES ($1::uuid, $2::uuid, $3, $4::uuid, $5::uuid, $6, $7::numeric, $8::numeric, $9::numeric, $10, $11::vector, $12)
