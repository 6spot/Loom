INSERT INTO loom_event_participant
(timeline_id, event_id, participant_order, entity_id, role)
VALUES ($1::uuid, $2::uuid, $3, $4::uuid, $5);
