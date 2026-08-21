-- Loom v0 authoritative PostgreSQL schema.
--
-- This schema preserves the Runtime contracts proven by the in-memory adapter.
-- World semantic time is stored as signed BIGINT coordinates. Runtime/platform
-- time is also stored as signed BIGINT, but only in explicitly operational Work
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
    world_time BIGINT NOT NULL DEFAULT 0
);

CREATE INDEX loom_timeline_world_idx ON loom_timeline (world_id);

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
        REFERENCES loom_event(timeline_id, event_id) ON DELETE CASCADE,
    FOREIGN KEY (timeline_id, cause_event_id)
        REFERENCES loom_event(timeline_id, event_id) ON DELETE RESTRICT
);

CREATE INDEX loom_event_causal_link_cause_idx
    ON loom_event_causal_link (timeline_id, cause_event_id, event_id);

CREATE TABLE loom_work (
    timeline_id UUID NOT NULL REFERENCES loom_timeline(timeline_id) ON DELETE CASCADE,
    work_id UUID NOT NULL,
    handler TEXT NOT NULL,
    schema_revision BIGINT NOT NULL
        CHECK (schema_revision BETWEEN 0 AND 4294967295),
    payload JSONB NOT NULL,
    due_world_time BIGINT,
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
    FOREIGN KEY (timeline_id, causal_event_id)
        REFERENCES loom_event(timeline_id, event_id) ON DELETE RESTRICT,
    FOREIGN KEY (timeline_id, origin_work_id)
        REFERENCES loom_work(timeline_id, work_id) ON DELETE RESTRICT,
    CHECK ((lease_claimed_until IS NULL) = (lease_fence IS NULL))
);

CREATE INDEX loom_work_claim_idx
    ON loom_work (timeline_id, status, available_at, due_world_time, work_id)
    WHERE status = 'pending';
