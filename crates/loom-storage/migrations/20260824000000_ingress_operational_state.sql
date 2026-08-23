-- M8-T2: durable Ingress identity, idempotency and operational lifecycle.
--
-- This table is Platform Operational State. It is intentionally separate from
-- Timeline/Event/Work authority: acceptance, claim, retry and terminal error
-- do not advance a Timeline or append a World Event.

CREATE TABLE loom_ingress (
    ingress_id TEXT PRIMARY KEY,
    idempotency_scope TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    source TEXT NOT NULL,
    source_external_id TEXT,
    source_metadata JSONB NOT NULL,
    world_id UUID NOT NULL REFERENCES loom_world(world_id),
    timeline_id UUID NOT NULL REFERENCES loom_timeline(timeline_id),
    authorization_context JSONB NOT NULL,
    source_time TEXT,
    platform_time TEXT,
    received_at BIGINT NOT NULL,
    invocation JSONB NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('accepted', 'processing', 'retryable', 'completed', 'failed')),
    attempt_count BIGINT NOT NULL CHECK (attempt_count BETWEEN 0 AND 4294967295),
    claim_fence NUMERIC(20, 0) NOT NULL CHECK (claim_fence BETWEEN 0 AND 18446744073709551615),
    available_at BIGINT NOT NULL,
    lease_claimed_until BIGINT,
    lease_fence NUMERIC(20, 0),
    last_error_code TEXT,
    last_error_message TEXT,
    completed_session_id UUID REFERENCES loom_execution_session(session_id),
    completed_event_refs JSONB NOT NULL,
    completion JSONB,
    completed_at BIGINT,
    record JSONB NOT NULL,
    UNIQUE (idempotency_scope, idempotency_key),
    CHECK ((lease_claimed_until IS NULL) = (lease_fence IS NULL)),
    CHECK ((status = 'processing') = (lease_claimed_until IS NOT NULL)),
    CHECK ((completed_session_id IS NULL) = (status <> 'completed')),
    CHECK ((completed_at IS NULL) = (status NOT IN ('completed', 'failed')))
);

CREATE INDEX loom_ingress_claim_idx
    ON loom_ingress (status, available_at, lease_claimed_until, ingress_id);
