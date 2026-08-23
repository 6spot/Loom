SELECT GREATEST(
    COALESCE(MAX(logical_schedule_order), 0),
    (SELECT logical_schedule_order FROM loom_timeline WHERE timeline_id = $1::uuid)
)::text AS logical_schedule_order
FROM loom_work
WHERE timeline_id = $1::uuid;
