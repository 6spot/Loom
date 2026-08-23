SELECT work_id::text AS work_id
FROM loom_work
WHERE timeline_id = $1::uuid
  AND status = 'pending'
  AND effective_due_world_time <= $2
ORDER BY effective_due_world_time, logical_schedule_order
LIMIT 1;
