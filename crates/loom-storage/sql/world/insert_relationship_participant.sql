INSERT INTO loom_relationship_participant
(timeline_id, relationship_id, participant_order, entity_id, role)
VALUES ($1::uuid, $2::uuid, $3, $4::uuid, $5);
