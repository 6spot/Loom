INSERT INTO loom_relationship (timeline_id, relationship_id, relationship_type, active)
SELECT $1::uuid, relationship_id, relationship_type, active
FROM loom_relationship
WHERE timeline_id = $2::uuid
