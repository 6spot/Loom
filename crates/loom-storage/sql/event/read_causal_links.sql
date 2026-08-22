SELECT cause_event_id::text AS cause_event_id
FROM loom_event_causal_link
WHERE timeline_id = $1::uuid
  AND event_id = $2::uuid
ORDER BY causal_order
