INSERT INTO loom_event_causal_link
(timeline_id, event_id, causal_order, cause_event_id)
VALUES ($1::uuid, $2::uuid, $3, $4::uuid);
