SELECT 1
FROM loom_world
WHERE world_id = $1::uuid
FOR UPDATE;
