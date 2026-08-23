SELECT head_event_seq::text AS head_event_seq,
       state_revision::text AS state_revision,
       world_time,
       chronology_budget_world_time,
       chronology_budget_consumed::text AS chronology_budget_consumed,
       logical_schedule_order::text AS logical_schedule_order
FROM loom_timeline
WHERE timeline_id = $1::uuid
FOR UPDATE;
