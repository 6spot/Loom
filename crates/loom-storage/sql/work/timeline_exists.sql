SELECT EXISTS (
    SELECT 1
    FROM loom_timeline
    WHERE timeline_id = $1::uuid
)
