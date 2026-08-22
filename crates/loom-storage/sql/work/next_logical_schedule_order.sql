SELECT COALESCE(MAX(logical_schedule_order), 0)::text AS logical_schedule_order
FROM loom_work
WHERE timeline_id = $1::uuid;
