SELECT event_id::text AS event_id
FROM loom_event
WHERE timeline_id = $1::uuid
  AND event_seq <= $2::numeric
ORDER BY event_seq DESC
LIMIT 1
