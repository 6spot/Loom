SELECT work_id::text AS work_id,
       effective_due_world_time
FROM loom_work
WHERE timeline_id = $1::uuid
  AND status = 'pending'
ORDER BY effective_due_world_time, logical_schedule_order
LIMIT 1;
