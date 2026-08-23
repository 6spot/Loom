WITH RECURSIVE timeline_segments(timeline_id, upper_event_seq, lower_event_seq) AS (
    SELECT
        timeline_id,
        head_event_seq::numeric(20, 0),
        COALESCE(fork_parent_head_event_seq, 0::numeric(20, 0))::numeric(20, 0)
    FROM loom_timeline
    WHERE timeline_id = $1::uuid

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
)
SELECT event.event_id::text
FROM timeline_segments
JOIN loom_event AS event
  ON event.timeline_id = timeline_segments.timeline_id
 AND event.event_seq > timeline_segments.lower_event_seq
 AND event.event_seq <= timeline_segments.upper_event_seq
