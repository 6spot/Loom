SELECT EXISTS (
    SELECT 1 FROM loom_event
    WHERE timeline_id = $1::uuid AND event_id = $2::uuid
);
