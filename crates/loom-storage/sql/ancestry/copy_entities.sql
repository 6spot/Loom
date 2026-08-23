INSERT INTO loom_entity (timeline_id, entity_id)
SELECT $1::uuid, entity_id
FROM loom_entity
WHERE timeline_id = $2::uuid
