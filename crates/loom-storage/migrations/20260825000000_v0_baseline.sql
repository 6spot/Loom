-- Loom v0 authoritative PostgreSQL schema.
--
-- The former M2-M9 migrations were development history only. V0 has no
-- production rows to preserve, so a fresh database receives the final
-- authority model directly rather than replaying transitional ALTER/UPDATE
-- steps or carrying compatibility state for pre-V0 schemas.
--
-- World semantic time is stored as signed BIGINT coordinates. Runtime/platform
-- time is also stored as signed BIGINT, but only in explicitly operational
-- columns; neither is interpreted as a PostgreSQL wall-clock timestamp.
--
-- EventSeq, StateRevision and Work claim fences are Rust u64 values. PostgreSQL
-- BIGINT is signed and cannot represent the full u64 domain, so those values use
-- NUMERIC(20,0) with explicit range constraints rather than silently narrowing
-- the Runtime contract.

CREATE TABLE loom_world (
    world_id UUID PRIMARY KEY
);

CREATE TABLE loom_timeline (
    timeline_id UUID PRIMARY KEY,
    world_id UUID NOT NULL REFERENCES loom_world(world_id) ON DELETE RESTRICT,
    head_event_seq NUMERIC(20, 0) NOT NULL DEFAULT 0
        CHECK (head_event_seq BETWEEN 0 AND 18446744073709551615),
    state_revision NUMERIC(20, 0) NOT NULL DEFAULT 0
        CHECK (state_revision BETWEEN 0 AND 18446744073709551615),
    world_time BIGINT NOT NULL DEFAULT 0,
    chronology_budget_world_time BIGINT NOT NULL DEFAULT 0,
    chronology_budget_consumed NUMERIC(20, 0) NOT NULL DEFAULT 0
        CHECK (chronology_budget_consumed BETWEEN 0 AND 18446744073709551615),
    parent_timeline_id UUID REFERENCES loom_timeline(timeline_id) ON DELETE RESTRICT,
    fork_parent_head_event_seq NUMERIC(20, 0)
        CHECK (fork_parent_head_event_seq IS NULL
            OR fork_parent_head_event_seq BETWEEN 0 AND 18446744073709551615),
    fork_parent_state_revision NUMERIC(20, 0)
        CHECK (fork_parent_state_revision IS NULL
            OR fork_parent_state_revision BETWEEN 0 AND 18446744073709551615),
    fork_parent_event_timeline_id UUID,
    fork_parent_event_id UUID,
    logical_schedule_order NUMERIC(20, 0) NOT NULL DEFAULT 0
        CHECK (logical_schedule_order BETWEEN 0 AND 18446744073709551615),
    CHECK (
        (parent_timeline_id IS NULL
            AND fork_parent_head_event_seq IS NULL
            AND fork_parent_state_revision IS NULL
            AND fork_parent_event_timeline_id IS NULL
            AND fork_parent_event_id IS NULL)
        OR (parent_timeline_id IS NOT NULL
            AND fork_parent_head_event_seq IS NOT NULL
            AND fork_parent_state_revision IS NOT NULL
            AND ((fork_parent_event_timeline_id IS NULL
                    AND fork_parent_event_id IS NULL)
                OR (fork_parent_event_timeline_id IS NOT NULL
                    AND fork_parent_event_id IS NOT NULL)))
    )
);

CREATE INDEX loom_timeline_world_idx ON loom_timeline (world_id);
CREATE INDEX loom_timeline_parent_idx ON loom_timeline (parent_timeline_id);

CREATE TABLE loom_entity (
    timeline_id UUID NOT NULL REFERENCES loom_timeline(timeline_id) ON DELETE CASCADE,
    entity_id UUID NOT NULL,
    PRIMARY KEY (timeline_id, entity_id)
);

CREATE TABLE loom_relationship (
    timeline_id UUID NOT NULL REFERENCES loom_timeline(timeline_id) ON DELETE CASCADE,
    relationship_id UUID NOT NULL,
    relationship_type TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (timeline_id, relationship_id)
);

CREATE TABLE loom_relationship_participant (
    timeline_id UUID NOT NULL,
    relationship_id UUID NOT NULL,
    participant_order INTEGER NOT NULL CHECK (participant_order >= 0),
    entity_id UUID NOT NULL,
    role TEXT NOT NULL,
    PRIMARY KEY (timeline_id, relationship_id, participant_order),
    UNIQUE (timeline_id, relationship_id, entity_id),
    FOREIGN KEY (timeline_id, relationship_id)
        REFERENCES loom_relationship(timeline_id, relationship_id) ON DELETE CASCADE,
    FOREIGN KEY (timeline_id, entity_id)
        REFERENCES loom_entity(timeline_id, entity_id) ON DELETE RESTRICT
);

CREATE TABLE loom_entity_facet (
    timeline_id UUID NOT NULL,
    entity_id UUID NOT NULL,
    facet_type TEXT NOT NULL,
    schema_revision BIGINT NOT NULL
        CHECK (schema_revision BETWEEN 0 AND 4294967295),
    value JSONB NOT NULL,
    PRIMARY KEY (timeline_id, entity_id, facet_type),
    FOREIGN KEY (timeline_id, entity_id)
        REFERENCES loom_entity(timeline_id, entity_id) ON DELETE CASCADE
);

CREATE TABLE loom_relationship_facet (
    timeline_id UUID NOT NULL,
    relationship_id UUID NOT NULL,
    facet_type TEXT NOT NULL,
    schema_revision BIGINT NOT NULL
        CHECK (schema_revision BETWEEN 0 AND 4294967295),
    value JSONB NOT NULL,
    PRIMARY KEY (timeline_id, relationship_id, facet_type),
    FOREIGN KEY (timeline_id, relationship_id)
        REFERENCES loom_relationship(timeline_id, relationship_id) ON DELETE CASCADE
);

CREATE TABLE loom_event (
    timeline_id UUID NOT NULL REFERENCES loom_timeline(timeline_id) ON DELETE CASCADE,
    event_id UUID NOT NULL,
    event_seq NUMERIC(20, 0) NOT NULL
        CHECK (event_seq BETWEEN 1 AND 18446744073709551615),
    event_type TEXT NOT NULL,
    schema_revision BIGINT NOT NULL
        CHECK (schema_revision BETWEEN 0 AND 4294967295),
    occurred_at BIGINT NOT NULL,
    payload JSONB NOT NULL,
    effects JSONB NOT NULL,
    PRIMARY KEY (timeline_id, event_id),
    UNIQUE (timeline_id, event_seq)
);

CREATE INDEX loom_event_type_idx ON loom_event (timeline_id, event_type, event_seq);
CREATE INDEX loom_event_world_time_idx ON loom_event (timeline_id, occurred_at, event_seq);

CREATE TABLE loom_event_participant (
    timeline_id UUID NOT NULL,
    event_id UUID NOT NULL,
    participant_order INTEGER NOT NULL CHECK (participant_order >= 0),
    entity_id UUID NOT NULL,
    role TEXT NOT NULL,
    PRIMARY KEY (timeline_id, event_id, participant_order),
    FOREIGN KEY (timeline_id, event_id)
        REFERENCES loom_event(timeline_id, event_id) ON DELETE CASCADE,
    FOREIGN KEY (timeline_id, entity_id)
        REFERENCES loom_entity(timeline_id, entity_id) ON DELETE RESTRICT
);

CREATE INDEX loom_event_participant_entity_idx
    ON loom_event_participant (timeline_id, entity_id, event_id);

CREATE TABLE loom_event_relationship_ref (
    timeline_id UUID NOT NULL,
    event_id UUID NOT NULL,
    reference_order INTEGER NOT NULL CHECK (reference_order >= 0),
    relationship_id UUID NOT NULL,
    role TEXT NOT NULL,
    PRIMARY KEY (timeline_id, event_id, reference_order),
    FOREIGN KEY (timeline_id, event_id)
        REFERENCES loom_event(timeline_id, event_id) ON DELETE CASCADE,
    FOREIGN KEY (timeline_id, relationship_id)
        REFERENCES loom_relationship(timeline_id, relationship_id) ON DELETE RESTRICT
);

CREATE INDEX loom_event_relationship_ref_relationship_idx
    ON loom_event_relationship_ref (timeline_id, relationship_id, event_id);

CREATE TABLE loom_event_causal_link (
    timeline_id UUID NOT NULL,
    event_id UUID NOT NULL,
    causal_order INTEGER NOT NULL CHECK (causal_order >= 0),
    cause_event_id UUID NOT NULL,
    PRIMARY KEY (timeline_id, event_id, causal_order),
    FOREIGN KEY (timeline_id, event_id)
        REFERENCES loom_event(timeline_id, event_id) ON DELETE CASCADE
);

CREATE INDEX loom_event_causal_link_cause_idx
    ON loom_event_causal_link (timeline_id, cause_event_id, event_id);

CREATE TABLE loom_work (
    timeline_id UUID NOT NULL REFERENCES loom_timeline(timeline_id) ON DELETE CASCADE,
    work_id UUID NOT NULL,
    target_kind TEXT NOT NULL,
    target_owner TEXT,
    target_handler TEXT,
    target_agent_id UUID,
    target_cognition TEXT,
    schema_revision BIGINT NOT NULL
        CHECK (schema_revision BETWEEN 0 AND 4294967295),
    payload JSONB NOT NULL,
    effective_due_world_time BIGINT NOT NULL,
    logical_schedule_order NUMERIC(20, 0) NOT NULL
        CHECK (logical_schedule_order BETWEEN 1 AND 18446744073709551615),
    causal_event_id UUID,
    origin_work_id UUID,
    status TEXT NOT NULL
        CHECK (status IN ('pending', 'completed', 'cancelled', 'dead')),
    attempt_count BIGINT NOT NULL DEFAULT 0
        CHECK (attempt_count BETWEEN 0 AND 4294967295),
    claim_generation NUMERIC(20, 0) NOT NULL DEFAULT 0
        CHECK (claim_generation BETWEEN 0 AND 18446744073709551615),
    available_at BIGINT NOT NULL,
    last_error TEXT,
    lease_claimed_until BIGINT,
    lease_fence NUMERIC(20, 0)
        CHECK (lease_fence BETWEEN 0 AND 18446744073709551615),
    PRIMARY KEY (timeline_id, work_id),
    FOREIGN KEY (timeline_id, target_agent_id)
        REFERENCES loom_entity(timeline_id, entity_id) ON DELETE RESTRICT,
    CHECK ((lease_claimed_until IS NULL) = (lease_fence IS NULL)),
    CHECK (
        (
            target_kind = 'capability_work'
            AND target_handler IS NOT NULL
            AND target_agent_id IS NULL
            AND target_cognition IS NULL
        )
        OR (
            target_kind = 'agency_wake'
            AND target_handler IS NULL
            AND target_owner IS NULL
            AND target_agent_id IS NOT NULL
            AND target_cognition IS NOT NULL
            AND target_cognition <> ''
        )
    )
);

CREATE INDEX loom_work_claim_idx
    ON loom_work (
        timeline_id,
        status,
        effective_due_world_time,
        logical_schedule_order,
        available_at
    )
    WHERE status = 'pending';

CREATE TABLE loom_world_runtime_binding (
    world_id UUID PRIMARY KEY REFERENCES loom_world(world_id) ON DELETE RESTRICT,
    binding JSONB NOT NULL
);

CREATE TABLE loom_runtime_revision (
    revision_id TEXT PRIMARY KEY,
    descriptor JSONB NOT NULL
);

CREATE TABLE loom_runtime_active_revision (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    revision_id TEXT REFERENCES loom_runtime_revision(revision_id) ON DELETE RESTRICT,
    activation_generation NUMERIC(20, 0) NOT NULL DEFAULT 0
        CHECK (activation_generation BETWEEN 0 AND 18446744073709551615),
    activated_at BIGINT,
    CHECK ((revision_id IS NULL) = (activated_at IS NULL))
);

INSERT INTO loom_runtime_active_revision (singleton)
VALUES (TRUE);

CREATE TABLE loom_execution_session (
    session_id UUID PRIMARY KEY,
    world_id UUID NOT NULL,
    timeline_id UUID NOT NULL,
    origin TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('Started', 'Committed', 'NoChange', 'Rejected', 'Failed', 'Blocked')),
    started_at BIGINT NOT NULL,
    ended_at BIGINT,
    record JSONB NOT NULL,
    CHECK ((status = 'Started') = (ended_at IS NULL))
);

CREATE INDEX loom_execution_session_timeline_idx
    ON loom_execution_session (timeline_id, started_at, session_id);

CREATE TABLE loom_logical_journal (
    timeline_id UUID NOT NULL REFERENCES loom_timeline(timeline_id) ON DELETE CASCADE,
    after_state_revision NUMERIC(20, 0) NOT NULL
        CHECK (after_state_revision BETWEEN 1 AND 18446744073709551615),
    before_head_event_seq NUMERIC(20, 0) NOT NULL
        CHECK (before_head_event_seq BETWEEN 0 AND 18446744073709551615),
    before_state_revision NUMERIC(20, 0) NOT NULL
        CHECK (before_state_revision BETWEEN 0 AND 18446744073709551615),
    after_head_event_seq NUMERIC(20, 0) NOT NULL
        CHECK (after_head_event_seq BETWEEN 0 AND 18446744073709551615),
    world_time_before BIGINT,
    world_time_after BIGINT,
    event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    work_transitions JSONB NOT NULL DEFAULT '[]'::jsonb,
    provenance JSONB,
    chronology_budget_world_time BIGINT,
    chronology_budget_before NUMERIC(20, 0)
        CHECK (chronology_budget_before IS NULL OR chronology_budget_before BETWEEN 0 AND 18446744073709551615),
    chronology_budget_after NUMERIC(20, 0)
        CHECK (chronology_budget_after IS NULL OR chronology_budget_after BETWEEN 0 AND 18446744073709551615),
    PRIMARY KEY (timeline_id, after_state_revision),
    CHECK ((world_time_before IS NULL) = (world_time_after IS NULL)),
    CHECK ((chronology_budget_world_time IS NULL)
        = (chronology_budget_before IS NULL AND chronology_budget_after IS NULL)),
    CHECK (jsonb_typeof(event_ids) = 'array'),
    CHECK (jsonb_typeof(work_transitions) = 'array'),
    CHECK (provenance IS NULL OR jsonb_typeof(provenance) = 'object')
);

CREATE INDEX loom_logical_journal_order_idx
    ON loom_logical_journal (timeline_id, after_state_revision);

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE loom_semantic_projection_index (
    world_id UUID NOT NULL REFERENCES loom_world(world_id) ON DELETE CASCADE,
    timeline_id UUID NOT NULL REFERENCES loom_timeline(timeline_id) ON DELETE CASCADE,
    index_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_type_id TEXT NOT NULL,
    source_schema_revision BIGINT NOT NULL
        CHECK (source_schema_revision BETWEEN 0 AND 4294967295),
    schema_revision BIGINT NOT NULL
        CHECK (schema_revision BETWEEN 0 AND 4294967295),
    projection_revision NUMERIC(20, 0) NOT NULL
        CHECK (projection_revision BETWEEN 1 AND 18446744073709551615),
    model_revision TEXT NOT NULL CHECK (model_revision <> ''),
    dimensions INTEGER NOT NULL CHECK (dimensions BETWEEN 1 AND 4096),
    metric TEXT NOT NULL CHECK (metric IN ('cosine', 'euclidean', 'inner_product')),
    PRIMARY KEY (world_id, timeline_id, index_id),
    CHECK (source_kind <> ''),
    CHECK (source_type_id <> '')
);

CREATE TABLE loom_semantic_projection_row (
    world_id UUID NOT NULL,
    timeline_id UUID NOT NULL,
    index_id TEXT NOT NULL,
    source_timeline_id UUID NOT NULL,
    source_event_id UUID NOT NULL,
    source_hash TEXT NOT NULL CHECK (source_hash <> ''),
    source_head_event_seq NUMERIC(20, 0) NOT NULL
        CHECK (source_head_event_seq BETWEEN 0 AND 18446744073709551615),
    source_state_revision NUMERIC(20, 0) NOT NULL
        CHECK (source_state_revision BETWEEN 0 AND 18446744073709551615),
    projection_revision NUMERIC(20, 0) NOT NULL
        CHECK (projection_revision BETWEEN 1 AND 18446744073709551615),
    model_revision TEXT NOT NULL CHECK (model_revision <> ''),
    vector_data vector NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions BETWEEN 1 AND 4096),
    PRIMARY KEY (
        world_id,
        timeline_id,
        index_id,
        source_timeline_id,
        source_event_id
    ),
    FOREIGN KEY (world_id, timeline_id, index_id)
        REFERENCES loom_semantic_projection_index(world_id, timeline_id, index_id)
        ON DELETE CASCADE,
    CHECK (vector_dims(vector_data) = dimensions)
);

CREATE INDEX loom_semantic_projection_lookup_idx
    ON loom_semantic_projection_row (
        world_id,
        timeline_id,
        index_id,
        projection_revision,
        source_timeline_id,
        source_event_id
    );

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

CREATE TABLE loom_runtime_revision_activation (
    activation_generation NUMERIC(20, 0) PRIMARY KEY
        CHECK (activation_generation BETWEEN 1 AND 18446744073709551615),
    revision_id TEXT NOT NULL REFERENCES loom_runtime_revision(revision_id)
        ON DELETE RESTRICT,
    activated_at BIGINT NOT NULL
);

CREATE TABLE loom_execution_session_event (
    timeline_id UUID NOT NULL,
    event_id UUID NOT NULL,
    event_seq NUMERIC(20, 0) NOT NULL
        CHECK (event_seq BETWEEN 1 AND 18446744073709551615),
    session_id UUID NOT NULL
        REFERENCES loom_execution_session(session_id) ON DELETE RESTRICT,
    PRIMARY KEY (timeline_id, event_id),
    UNIQUE (session_id, event_seq),
    FOREIGN KEY (timeline_id, event_id)
        REFERENCES loom_event(timeline_id, event_id) ON DELETE RESTRICT
);

CREATE INDEX loom_execution_session_event_session_idx
    ON loom_execution_session_event (session_id, event_seq, timeline_id, event_id);
