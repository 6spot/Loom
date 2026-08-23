INSERT INTO loom_relationship_participant
    (timeline_id, relationship_id, participant_order, entity_id, role)
SELECT $1::uuid, relationship_id, participant_order, entity_id, role
FROM loom_relationship_participant
WHERE timeline_id = $2::uuid
