SELECT entity_id::text AS entity_id
FROM loom_entity AS entity
JOIN loom_timeline AS timeline USING (timeline_id)
WHERE entity.timeline_id = $1::uuid
  AND entity.entity_id = $2::uuid
  AND timeline.head_event_seq = $3::numeric
  AND timeline.state_revision = $4::numeric
