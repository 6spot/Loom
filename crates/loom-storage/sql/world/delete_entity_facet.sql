DELETE FROM loom_entity_facet
WHERE timeline_id = $1::uuid
  AND entity_id = $2::uuid
  AND facet_type = $3;
