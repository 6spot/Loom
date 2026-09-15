-- C3-T10: append-only global history editions over already published narrative
-- fragments.  The edition tables are Chronicle application persistence; they
-- never become an authority for source facts or review decisions.

CREATE TABLE chronicle.history_editions (
    edition_version text PRIMARY KEY CHECK (edition_version ~ '^[0-9a-f]{64}$'),
    manifest_sha256 text NOT NULL UNIQUE CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    fragment_count integer NOT NULL CHECK (fragment_count > 0),
    paragraph_count integer NOT NULL CHECK (paragraph_count > 0),
    manifest jsonb NOT NULL,
    metadata jsonb NOT NULL,
    job_id uuid REFERENCES chronicle.ingestion_jobs(job_id) ON DELETE RESTRICT,
    publication_sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    published_at timestamptz NOT NULL DEFAULT now(),
    CHECK (edition_version = manifest_sha256)
);

-- A fragment row is a source snapshot plus an optional source-record handle.
-- Keeping the bounded fragment body here lets a historical edition remain
-- readable even if a deployment later changes how the old narrative source
-- table is exposed.  It is not an editable facts store and is immutable after
-- publication.
CREATE TABLE chronicle.history_edition_fragments (
    edition_version text NOT NULL REFERENCES chronicle.history_editions(edition_version) ON DELETE RESTRICT,
    fragment_ordinal integer NOT NULL CHECK (fragment_ordinal >= 0),
    fragment_version text NOT NULL,
    publication_id text NOT NULL,
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    coverage jsonb NOT NULL,
    fragment_payload jsonb NOT NULL,
    source_publication_version text,
    PRIMARY KEY (edition_version, fragment_ordinal),
    UNIQUE (edition_version, fragment_version),
    UNIQUE (edition_version, publication_id)
);

CREATE TABLE chronicle.history_edition_paragraph_index (
    edition_version text NOT NULL REFERENCES chronicle.history_editions(edition_version) ON DELETE RESTRICT,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    paragraph_id text NOT NULL CHECK (paragraph_id ~ '^hp_[0-9a-f]{24}$'),
    fragment_version text NOT NULL,
    source_paragraph_id text NOT NULL,
    source_ordinal integer NOT NULL CHECK (source_ordinal >= 0),
    phase_id text NOT NULL CHECK (phase_id ~ '^hphase_[0-9a-f]{24}$'),
    conclusion_ids jsonb NOT NULL,
    content_ref jsonb NOT NULL,
    PRIMARY KEY (edition_version, ordinal),
    UNIQUE (edition_version, paragraph_id)
);

CREATE INDEX history_edition_paragraph_page_idx
    ON chronicle.history_edition_paragraph_index(edition_version, ordinal);

CREATE TABLE chronicle.history_edition_phase_index (
    edition_version text NOT NULL REFERENCES chronicle.history_editions(edition_version) ON DELETE RESTRICT,
    phase_id text NOT NULL CHECK (phase_id ~ '^hphase_[0-9a-f]{24}$'),
    fragment_version text NOT NULL,
    source_phase_id text NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (edition_version, phase_id)
);

CREATE TABLE chronicle.history_edition_conclusion_index (
    edition_version text NOT NULL REFERENCES chronicle.history_editions(edition_version) ON DELETE RESTRICT,
    conclusion_id text NOT NULL CHECK (conclusion_id ~ '^hcon_[0-9a-f]{24}$'),
    fragment_version text NOT NULL,
    source_conclusion_id text NOT NULL,
    phase_ids jsonb NOT NULL,
    evidence jsonb NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (edition_version, conclusion_id)
);

CREATE INDEX history_edition_conclusion_lookup_idx
    ON chronicle.history_edition_conclusion_index(edition_version, conclusion_id);

-- The pointer is deliberately a one-row mutable frontier.  It points only to
-- an already committed immutable edition and is updated last in the publish
-- transaction, so a failed/lost-lease publish cannot expose partial indexes.
CREATE TABLE chronicle.history_edition_latest (
    pointer_key text PRIMARY KEY CHECK (pointer_key = 'history'),
    edition_version text NOT NULL REFERENCES chronicle.history_editions(edition_version) ON DELETE RESTRICT,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE chronicle.history_edition_drafts (
    draft_id uuid PRIMARY KEY,
    baseline_manifest_sha256 text CHECK (baseline_manifest_sha256 IS NULL OR baseline_manifest_sha256 ~ '^[0-9a-f]{64}$'),
    fragment_snapshots jsonb NOT NULL,
    boundary_reviews jsonb NOT NULL DEFAULT '[]'::jsonb,
    navigation jsonb,
    lineage jsonb,
    status text NOT NULL CHECK (status IN ('draft', 'published', 'conflict')),
    edition_version text REFERENCES chronicle.history_editions(edition_version) ON DELETE RESTRICT,
    job_id uuid REFERENCES chronicle.ingestion_jobs(job_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((status = 'published' AND edition_version IS NOT NULL)
        OR (status IN ('draft', 'conflict')))
);

CREATE INDEX history_edition_drafts_status_idx
    ON chronicle.history_edition_drafts(status, updated_at DESC, draft_id);

CREATE TRIGGER history_editions_immutable
    BEFORE UPDATE OR DELETE ON chronicle.history_editions
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_reading_mutation();
CREATE TRIGGER history_edition_fragments_immutable
    BEFORE UPDATE OR DELETE ON chronicle.history_edition_fragments
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_reading_mutation();
CREATE TRIGGER history_edition_paragraph_index_immutable
    BEFORE UPDATE OR DELETE ON chronicle.history_edition_paragraph_index
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_reading_mutation();
CREATE TRIGGER history_edition_phase_index_immutable
    BEFORE UPDATE OR DELETE ON chronicle.history_edition_phase_index
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_reading_mutation();
CREATE TRIGGER history_edition_conclusion_index_immutable
    BEFORE UPDATE OR DELETE ON chronicle.history_edition_conclusion_index
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_reading_mutation();

-- Friendly read names used by operators and migration checks.  The physical
-- index names above make the ownership obvious in query plans.
CREATE VIEW chronicle.history_edition_paragraphs AS
    SELECT * FROM chronicle.history_edition_paragraph_index;
CREATE VIEW chronicle.history_edition_phases AS
    SELECT * FROM chronicle.history_edition_phase_index;
CREATE VIEW chronicle.history_edition_conclusions AS
    SELECT * FROM chronicle.history_edition_conclusion_index;
