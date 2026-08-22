UPDATE loom_relationship
SET active = FALSE
WHERE timeline_id = $1::uuid AND relationship_id = $2::uuid;
