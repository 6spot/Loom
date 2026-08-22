SELECT active.revision_id,
       active.activation_generation::text AS activation_generation,
       active.activated_at,
       revision.descriptor
FROM loom_runtime_active_revision AS active
LEFT JOIN loom_runtime_revision AS revision
  ON revision.revision_id = active.revision_id
WHERE active.singleton = TRUE;
