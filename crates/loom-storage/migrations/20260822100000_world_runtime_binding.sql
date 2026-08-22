-- World-level Runtime Binding metadata is additive to the M3 World/Timeline
-- authority schema. Existing Worlds intentionally receive no implicit
-- "currently installed" row here; Runtime performs the explicit, one-time
-- compatibility ensure and persists its deterministic baseline descriptor.

CREATE TABLE loom_world_runtime_binding (
    world_id UUID PRIMARY KEY REFERENCES loom_world(world_id) ON DELETE RESTRICT,
    binding JSONB NOT NULL
);
