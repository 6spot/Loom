DELETE FROM loom_semantic_projection_index
WHERE world_id = $1::uuid
  AND timeline_id = $2::uuid
  AND index_id = $3
