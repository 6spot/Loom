SELECT world_time
FROM loom_timeline
WHERE timeline_id = $1::uuid
FOR UPDATE;
