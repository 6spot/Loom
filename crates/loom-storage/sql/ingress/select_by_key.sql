SELECT record
FROM loom_ingress
WHERE idempotency_scope = $1
  AND idempotency_key = $2
FOR UPDATE;
