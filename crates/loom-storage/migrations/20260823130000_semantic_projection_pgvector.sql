-- M7-T2: rebuildable semantic/vector projections.
--
-- These tables are deliberately separate from Event/State/Timeline logical
-- authority. They may be deleted and rebuilt without changing replay, fork or
-- any authoritative version. The vector extension is the only PostgreSQL
-- implementation detail exposed here; Runtime contracts use plain vectors.

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
    CHECK (source_type_id <> ''),
    FOREIGN KEY (timeline_id) REFERENCES loom_timeline(timeline_id) ON DELETE CASCADE
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
