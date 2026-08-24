SELECT timeline_id::text AS timeline_id,
       after_state_revision::text AS after_state_revision,
       before_head_event_seq::text AS before_head_event_seq,
       before_state_revision::text AS before_state_revision,
       after_head_event_seq::text AS after_head_event_seq,
       world_time_before,
       world_time_after,
       event_ids,
       work_transitions,
       provenance,
       chronology_budget_world_time,
       chronology_budget_before::text AS chronology_budget_before,
       chronology_budget_after::text AS chronology_budget_after
FROM loom_logical_journal
WHERE timeline_id = $1::uuid
ORDER BY after_state_revision ASC;
