SELECT EXISTS (
    SELECT 1 FROM loom_entity
    WHERE timeline_id = $1::uuid AND entity_id = $2::uuid
);
