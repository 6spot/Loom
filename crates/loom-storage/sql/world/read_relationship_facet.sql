SELECT
    relationship_facet.relationship_id::text AS owner_id,
    relationship_facet.facet_type,
    relationship_facet.schema_revision,
    relationship_facet.value
FROM loom_relationship_facet AS relationship_facet
JOIN loom_timeline AS timeline USING (timeline_id)
WHERE relationship_facet.timeline_id = $1::uuid
  AND relationship_facet.relationship_id = $2::uuid
  AND relationship_facet.facet_type = $3::text
  AND timeline.head_event_seq = $4::numeric
  AND timeline.state_revision = $5::numeric
