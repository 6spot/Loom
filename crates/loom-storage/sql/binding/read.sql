SELECT binding
FROM loom_world_runtime_binding
WHERE world_id = $1::uuid;
