SELECT EXISTS (
    SELECT 1 FROM loom_work
    WHERE timeline_id = $1::uuid AND work_id = $2::uuid
);
