DELETE FROM loom_relationship_facet
WHERE timeline_id = $1::uuid
  AND relationship_id = $2::uuid
  AND facet_type = $3;
