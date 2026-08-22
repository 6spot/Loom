SELECT head_event_seq::text AS head_event_seq,
       state_revision::text AS state_revision
FROM loom_timeline
WHERE timeline_id = $1::uuid
FOR UPDATE;
