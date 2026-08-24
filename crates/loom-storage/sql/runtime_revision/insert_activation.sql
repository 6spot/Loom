INSERT INTO loom_runtime_revision_activation (
    revision_id,
    activation_generation,
    activated_at
)
VALUES ($1, $2::numeric, $3);
