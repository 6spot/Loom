SELECT entity_id::text AS entity_id
FROM loom_entity
WHERE timeline_id = $1::uuid
ORDER BY entity_id
