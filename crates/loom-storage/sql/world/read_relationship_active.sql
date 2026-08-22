SELECT active
FROM loom_relationship
WHERE timeline_id = $1::uuid AND relationship_id = $2::uuid;
