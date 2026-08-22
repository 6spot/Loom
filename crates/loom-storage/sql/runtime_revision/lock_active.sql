SELECT revision_id,
       activation_generation::text AS activation_generation
FROM loom_runtime_active_revision
WHERE singleton = TRUE
FOR UPDATE;
