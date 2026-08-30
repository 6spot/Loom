-- Enumerate distinct Timeline targets that still have logical Pending Work.
--
-- Parameters:
--   $1: nullable exclusive cursor WorldId
--   $2: nullable exclusive cursor TimelineId
--   $3: validated positive bounded page size
--
-- The cursor is an operational enumeration frontier, not Work chronology.
-- Runtime validates the page-size bound before executing this read.
SELECT
    timeline.world_id::text AS world_id,
    timeline.timeline_id::text AS timeline_id
FROM loom_timeline AS timeline
WHERE (
    $1::uuid IS NULL
    OR (timeline.world_id, timeline.timeline_id) > ($1::uuid, $2::uuid)
)
  AND EXISTS (
      SELECT 1
      FROM loom_work AS work
      WHERE work.timeline_id = timeline.timeline_id
        AND work.status = 'pending'
  )
ORDER BY timeline.world_id, timeline.timeline_id
LIMIT $3::bigint;
