SELECT
    relationship.relationship_id::text AS relationship_id,
    relationship.relationship_type,
    relationship.active
FROM loom_relationship AS relationship
JOIN loom_timeline AS timeline USING (timeline_id)
WHERE relationship.timeline_id = $1::uuid
  AND relationship.relationship_id = $2::uuid
  AND timeline.head_event_seq = $3::numeric
  AND timeline.state_revision = $4::numeric
