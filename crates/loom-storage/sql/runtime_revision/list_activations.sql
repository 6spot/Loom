SELECT revision_id,
       activation_generation::text AS activation_generation,
       activated_at
FROM loom_runtime_revision_activation
ORDER BY activation_generation ASC;
