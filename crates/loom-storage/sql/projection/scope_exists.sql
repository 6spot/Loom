SELECT 1
FROM loom_timeline
WHERE timeline_id = $1::uuid
  AND world_id = $2::uuid
