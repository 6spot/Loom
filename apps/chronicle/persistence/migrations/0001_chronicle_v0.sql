CREATE SCHEMA IF NOT EXISTS chronicle;

CREATE TABLE IF NOT EXISTS chronicle.source_bundles (
    bundle_label text PRIMARY KEY,
    schema_version text NOT NULL,
    source_ref text NOT NULL,
    source_title text NOT NULL,
    artifact_sha256 text NOT NULL CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    source_payload jsonb NOT NULL,
    bundle_payload jsonb NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chronicle.staged_entities (
    bundle_label text NOT NULL REFERENCES chronicle.source_bundles(bundle_label) ON DELETE RESTRICT,
    record_ref text NOT NULL,
    payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL,
    PRIMARY KEY (bundle_label, record_ref)
);

CREATE TABLE IF NOT EXISTS chronicle.staged_events (
    bundle_label text NOT NULL REFERENCES chronicle.source_bundles(bundle_label) ON DELETE RESTRICT,
    record_ref text NOT NULL,
    payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL,
    PRIMARY KEY (bundle_label, record_ref)
);

CREATE TABLE IF NOT EXISTS chronicle.staged_claims (
    bundle_label text NOT NULL REFERENCES chronicle.source_bundles(bundle_label) ON DELETE RESTRICT,
    record_ref text NOT NULL,
    payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL,
    PRIMARY KEY (bundle_label, record_ref)
);

CREATE TABLE IF NOT EXISTS chronicle.staged_warnings (
    bundle_label text NOT NULL REFERENCES chronicle.source_bundles(bundle_label) ON DELETE RESTRICT,
    warning_index integer NOT NULL CHECK (warning_index >= 0),
    payload jsonb NOT NULL,
    PRIMARY KEY (bundle_label, warning_index)
);

CREATE TABLE IF NOT EXISTS chronicle.resolution_artifacts (
    artifact_sha256 text PRIMARY KEY CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    schema_name text NOT NULL,
    schema_version text NOT NULL,
    left_bundle_label text NOT NULL REFERENCES chronicle.source_bundles(bundle_label) ON DELETE RESTRICT,
    right_bundle_label text NOT NULL REFERENCES chronicle.source_bundles(bundle_label) ON DELETE RESTRICT,
    payload jsonb NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chronicle.resolution_entity_links (
    resolution_sha256 text NOT NULL REFERENCES chronicle.resolution_artifacts(artifact_sha256) ON DELETE RESTRICT,
    candidate_id text NOT NULL,
    left_bundle_label text NOT NULL,
    left_record_ref text NOT NULL,
    right_bundle_label text NOT NULL,
    right_record_ref text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('same_entity', 'not_same', 'uncertain')),
    confidence double precision NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    rationale text NOT NULL,
    signals jsonb NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (resolution_sha256, candidate_id),
    FOREIGN KEY (left_bundle_label, left_record_ref)
        REFERENCES chronicle.staged_entities(bundle_label, record_ref) ON DELETE RESTRICT,
    FOREIGN KEY (right_bundle_label, right_record_ref)
        REFERENCES chronicle.staged_entities(bundle_label, record_ref) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS chronicle.resolution_event_links (
    resolution_sha256 text NOT NULL REFERENCES chronicle.resolution_artifacts(artifact_sha256) ON DELETE RESTRICT,
    candidate_id text NOT NULL,
    left_bundle_label text NOT NULL,
    left_record_ref text NOT NULL,
    right_bundle_label text NOT NULL,
    right_record_ref text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('same_occurrence', 'related_occurrence', 'not_same', 'uncertain')),
    confidence double precision NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    rationale text NOT NULL,
    signals jsonb NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (resolution_sha256, candidate_id),
    FOREIGN KEY (left_bundle_label, left_record_ref)
        REFERENCES chronicle.staged_events(bundle_label, record_ref) ON DELETE RESTRICT,
    FOREIGN KEY (right_bundle_label, right_record_ref)
        REFERENCES chronicle.staged_events(bundle_label, record_ref) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS chronicle.resolution_warnings (
    resolution_sha256 text NOT NULL REFERENCES chronicle.resolution_artifacts(artifact_sha256) ON DELETE RESTRICT,
    warning_index integer NOT NULL CHECK (warning_index >= 0),
    payload jsonb NOT NULL,
    PRIMARY KEY (resolution_sha256, warning_index)
);

CREATE TABLE IF NOT EXISTS chronicle.canonical_catalogs (
    artifact_sha256 text PRIMARY KEY CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    schema_name text NOT NULL,
    schema_version text NOT NULL,
    payload jsonb NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chronicle.canonical_entities (
    canonical_id uuid PRIMARY KEY,
    first_catalog_sha256 text NOT NULL REFERENCES chronicle.canonical_catalogs(artifact_sha256) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS chronicle.canonical_events (
    canonical_id uuid PRIMARY KEY,
    first_catalog_sha256 text NOT NULL REFERENCES chronicle.canonical_catalogs(artifact_sha256) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS chronicle.canonical_catalog_entities (
    catalog_sha256 text NOT NULL REFERENCES chronicle.canonical_catalogs(artifact_sha256) ON DELETE RESTRICT,
    canonical_id uuid NOT NULL REFERENCES chronicle.canonical_entities(canonical_id) ON DELETE RESTRICT,
    PRIMARY KEY (catalog_sha256, canonical_id)
);

CREATE TABLE IF NOT EXISTS chronicle.canonical_catalog_events (
    catalog_sha256 text NOT NULL REFERENCES chronicle.canonical_catalogs(artifact_sha256) ON DELETE RESTRICT,
    canonical_id uuid NOT NULL REFERENCES chronicle.canonical_events(canonical_id) ON DELETE RESTRICT,
    PRIMARY KEY (catalog_sha256, canonical_id)
);

CREATE TABLE IF NOT EXISTS chronicle.canonical_entity_representations (
    bundle_label text NOT NULL,
    record_ref text NOT NULL,
    canonical_id uuid NOT NULL REFERENCES chronicle.canonical_entities(canonical_id) ON DELETE RESTRICT,
    first_catalog_sha256 text NOT NULL REFERENCES chronicle.canonical_catalogs(artifact_sha256) ON DELETE RESTRICT,
    PRIMARY KEY (bundle_label, record_ref),
    FOREIGN KEY (bundle_label, record_ref)
        REFERENCES chronicle.staged_entities(bundle_label, record_ref) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS canonical_entity_representations_canonical_idx
    ON chronicle.canonical_entity_representations(canonical_id);

CREATE TABLE IF NOT EXISTS chronicle.canonical_event_representations (
    bundle_label text NOT NULL,
    record_ref text NOT NULL,
    canonical_id uuid NOT NULL REFERENCES chronicle.canonical_events(canonical_id) ON DELETE RESTRICT,
    first_catalog_sha256 text NOT NULL REFERENCES chronicle.canonical_catalogs(artifact_sha256) ON DELETE RESTRICT,
    PRIMARY KEY (bundle_label, record_ref),
    FOREIGN KEY (bundle_label, record_ref)
        REFERENCES chronicle.staged_events(bundle_label, record_ref) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS canonical_event_representations_canonical_idx
    ON chronicle.canonical_event_representations(canonical_id);

CREATE TABLE IF NOT EXISTS chronicle.canonical_event_relations (
    relation_sha256 text PRIMARY KEY CHECK (relation_sha256 ~ '^[0-9a-f]{64}$'),
    relation_type text NOT NULL CHECK (relation_type = 'related_occurrence'),
    left_canonical_event_id uuid NOT NULL REFERENCES chronicle.canonical_events(canonical_id) ON DELETE RESTRICT,
    right_canonical_event_id uuid NOT NULL REFERENCES chronicle.canonical_events(canonical_id) ON DELETE RESTRICT,
    first_catalog_sha256 text NOT NULL REFERENCES chronicle.canonical_catalogs(artifact_sha256) ON DELETE RESTRICT,
    payload jsonb NOT NULL,
    CHECK (left_canonical_event_id <> right_canonical_event_id)
);

CREATE INDEX IF NOT EXISTS canonical_event_relations_left_idx
    ON chronicle.canonical_event_relations(left_canonical_event_id);
CREATE INDEX IF NOT EXISTS canonical_event_relations_right_idx
    ON chronicle.canonical_event_relations(right_canonical_event_id);

CREATE TABLE IF NOT EXISTS chronicle.canonical_catalog_relations (
    catalog_sha256 text NOT NULL REFERENCES chronicle.canonical_catalogs(artifact_sha256) ON DELETE RESTRICT,
    relation_sha256 text NOT NULL REFERENCES chronicle.canonical_event_relations(relation_sha256) ON DELETE RESTRICT,
    PRIMARY KEY (catalog_sha256, relation_sha256)
);

CREATE TABLE IF NOT EXISTS chronicle.canonical_event_relation_links (
    relation_sha256 text NOT NULL REFERENCES chronicle.canonical_event_relations(relation_sha256) ON DELETE RESTRICT,
    candidate_id text NOT NULL,
    left_bundle_label text NOT NULL,
    left_record_ref text NOT NULL,
    right_bundle_label text NOT NULL,
    right_record_ref text NOT NULL,
    PRIMARY KEY (
        relation_sha256,
        candidate_id,
        left_bundle_label,
        left_record_ref,
        right_bundle_label,
        right_record_ref
    ),
    FOREIGN KEY (left_bundle_label, left_record_ref)
        REFERENCES chronicle.staged_events(bundle_label, record_ref) ON DELETE RESTRICT,
    FOREIGN KEY (right_bundle_label, right_record_ref)
        REFERENCES chronicle.staged_events(bundle_label, record_ref) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS chronicle.canonical_warnings (
    catalog_sha256 text NOT NULL REFERENCES chronicle.canonical_catalogs(artifact_sha256) ON DELETE RESTRICT,
    warning_index integer NOT NULL CHECK (warning_index >= 0),
    payload jsonb NOT NULL,
    PRIMARY KEY (catalog_sha256, warning_index)
);

CREATE TABLE IF NOT EXISTS chronicle.import_sets (
    import_key text PRIMARY KEY CHECK (import_key ~ '^[0-9a-f]{64}$'),
    bundle_artifacts jsonb NOT NULL,
    resolution_artifacts jsonb NOT NULL,
    catalog_sha256 text NOT NULL REFERENCES chronicle.canonical_catalogs(artifact_sha256) ON DELETE RESTRICT,
    imported_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS resolution_entity_links_decision_idx
    ON chronicle.resolution_entity_links(decision);
CREATE INDEX IF NOT EXISTS resolution_event_links_decision_idx
    ON chronicle.resolution_event_links(decision);
