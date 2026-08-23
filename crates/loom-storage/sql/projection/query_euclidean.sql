SELECT
    source_timeline_id::text,
    source_event_id::text,
    source_hash,
    source_head_event_seq::text,
    source_state_revision::text,
    projection_revision::text,
    model_revision,
    (vector_data <-> $4::vector)::real AS distance
FROM loom_semantic_projection_row
WHERE world_id = $1::uuid
  AND timeline_id = $2::uuid
  AND index_id = $3
  AND projection_revision = $5::numeric
  AND model_revision = $6
ORDER BY distance ASC, source_timeline_id, source_event_id
LIMIT $7
