INSERT INTO loom_relationship
(timeline_id, relationship_id, relationship_type, active)
VALUES ($1::uuid, $2::uuid, $3, TRUE);
