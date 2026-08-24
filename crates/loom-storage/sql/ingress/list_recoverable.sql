SELECT ingress_id
FROM loom_ingress
WHERE available_at <= $1
  AND (
    status IN ('accepted', 'retryable')
    OR (status = 'processing' AND lease_claimed_until <= $1)
  )
ORDER BY received_at, ingress_id
LIMIT $2;
