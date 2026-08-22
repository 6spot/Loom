INSERT INTO loom_world_runtime_binding (world_id, binding)
VALUES ($1::uuid, $2::jsonb)
ON CONFLICT (world_id) DO NOTHING;
