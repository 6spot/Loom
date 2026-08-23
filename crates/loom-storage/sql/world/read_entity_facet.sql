SELECT
    entity_facet.entity_id::text AS owner_id,
    entity_facet.facet_type,
    entity_facet.schema_revision,
    entity_facet.value
FROM loom_entity_facet AS entity_facet
JOIN loom_timeline AS timeline USING (timeline_id)
WHERE entity_facet.timeline_id = $1::uuid
  AND entity_facet.entity_id = $2::uuid
  AND entity_facet.facet_type = $3::text
  AND timeline.head_event_seq = $4::numeric
  AND timeline.state_revision = $5::numeric
