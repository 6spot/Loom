INSERT INTO loom_ingress (
    ingress_id, idempotency_scope, idempotency_key, request_fingerprint,
    source, source_external_id, source_metadata, world_id, timeline_id,
    authorization_context, source_time, platform_time, received_at, invocation,
    status, attempt_count, claim_fence, available_at, lease_claimed_until,
    lease_fence, last_error_code, last_error_message, completed_session_id,
    completed_event_refs, completion, completed_at, record
)
VALUES (
    $1, $2, $3, $4, $5, $6, $7::jsonb, $8::uuid, $9::uuid, $10::jsonb,
    $11, $12, $13, $14::jsonb, $15, $16, $17::numeric, $18, $19, $20::numeric,
    $21, $22, $23::uuid, $24::jsonb, $25::jsonb, $26, $27::jsonb
)
ON CONFLICT (idempotency_scope, idempotency_key) DO NOTHING
RETURNING ingress_id;
