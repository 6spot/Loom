UPDATE loom_runtime_active_revision
SET revision_id = $1,
    activation_generation = $2::numeric,
    activated_at = $3
WHERE singleton = TRUE;
