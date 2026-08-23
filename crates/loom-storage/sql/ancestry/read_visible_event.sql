WITH RECURSIVE timeline_segments(timeline_id, upper_event_seq, lower_event_seq) AS (
    SELECT
        timeline.timeline_id,
        timeline.head_event_seq::numeric(20, 0),
        COALESCE(timeline.fork_parent_head_event_seq, 0::numeric(20, 0))::numeric(20, 0)
    FROM loom_timeline AS timeline
    WHERE timeline.timeline_id = $1::uuid
      AND timeline.head_event_seq = $3::numeric
      AND timeline.state_revision = $4::numeric

    UNION ALL

    SELECT
        parent.timeline_id,
        child_segment.lower_event_seq::numeric(20, 0),
        COALESCE(parent.fork_parent_head_event_seq, 0::numeric(20, 0))::numeric(20, 0)
    FROM timeline_segments AS child_segment
    JOIN loom_timeline AS child
      ON child.timeline_id = child_segment.timeline_id
    JOIN loom_timeline AS parent
      ON parent.timeline_id = child.parent_timeline_id
    WHERE child_segment.upper_event_seq >= child_segment.lower_event_seq
)
SELECT
    event.timeline_id::text AS timeline_id,
    event.event_id::text AS event_id,
    event.event_seq::text AS event_seq,
    event.event_type,
    event.schema_revision,
    event.occurred_at,
    event.payload,
    event.effects
FROM timeline_segments
JOIN loom_event AS event
  ON event.timeline_id = timeline_segments.timeline_id
 AND event.event_seq > timeline_segments.lower_event_seq
 AND event.event_seq <= timeline_segments.upper_event_seq
WHERE event.event_id = $2::uuid
ORDER BY event.event_seq
