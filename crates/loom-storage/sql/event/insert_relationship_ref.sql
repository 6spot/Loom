INSERT INTO loom_event_relationship_ref
(timeline_id, event_id, reference_order, relationship_id, role)
VALUES ($1::uuid, $2::uuid, $3, $4::uuid, $5);
