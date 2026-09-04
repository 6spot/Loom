-- Chronicle C1-T1 ingestion control-plane contract (GitHub #490).
--
-- Application-owned product persistence under CHRONICLE_DATABASE_URL.
-- This migration only ADDS new control-plane tables. It must not alter,
-- rewrite, or drop any C0 staged / resolution / canonical table created by
-- 0001_chronicle_v0.sql. C0 semantics stay byte-for-byte intact.
--
-- Authority boundary (Amendment 0006): these tables describe Chronicle's own
-- document ingestion orchestration. They are not Loom Runtime Scheduler/Work
-- authority, not Loom Storage semantics, and not historical-knowledge
-- authority (that remains the C0 staged -> resolution -> canonical path,
-- which assembled ingestion outputs feed into).
--
-- Immutability: document_revisions, ingestion_chunk_runs, and
-- ingestion_outputs are append-only audit history. UPDATE/DELETE on them is
-- rejected by triggers below. Replacing a source creates a new revision that
-- supersedes the old one; the old row is never modified or removed.

-- ---------------------------------------------------------------------------
-- Documents and immutable revisions
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS chronicle.documents (
    document_id uuid PRIMARY KEY CHECK (uuid_extract_version(document_id) = 7),
    title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 500),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chronicle.document_revisions (
    revision_id uuid PRIMARY KEY CHECK (uuid_extract_version(revision_id) = 7),
    document_id uuid NOT NULL REFERENCES chronicle.documents(document_id) ON DELETE RESTRICT,
    revision_number integer NOT NULL CHECK (revision_number >= 1),
    source_ref text NOT NULL CHECK (char_length(source_ref) BETWEEN 1 AND 1000),
    source_media_type text NOT NULL DEFAULT 'application/octet-stream'
        CHECK (char_length(source_media_type) BETWEEN 1 AND 200),
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    source_length_bytes bigint NOT NULL CHECK (source_length_bytes >= 0),
    manifest jsonb NOT NULL DEFAULT '{}'::jsonb,
    supersedes_revision_id uuid NULL REFERENCES chronicle.document_revisions(revision_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, revision_number),
    UNIQUE (document_id, source_sha256),
    CHECK (supersedes_revision_id IS NULL OR supersedes_revision_id <> revision_id)
);

CREATE INDEX IF NOT EXISTS document_revisions_document_idx
    ON chronicle.document_revisions(document_id, revision_number);
CREATE INDEX IF NOT EXISTS document_revisions_supersedes_idx
    ON chronicle.document_revisions(supersedes_revision_id);

-- Supersession must stay within one document: a revision may only supersede
-- an older revision of the same document.
CREATE OR REPLACE FUNCTION chronicle.check_revision_supersession()
RETURNS trigger AS $$
DECLARE
    prev_document uuid;
    prev_number integer;
BEGIN
    IF NEW.supersedes_revision_id IS NULL THEN
        IF NEW.revision_number <> 1 THEN
            RAISE EXCEPTION
                'first revision of a document must use revision_number 1 (got %)',
                NEW.revision_number;
        END IF;
        RETURN NEW;
    END IF;
    SELECT document_id, revision_number INTO prev_document, prev_number
    FROM chronicle.document_revisions
    WHERE revision_id = NEW.supersedes_revision_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'superseded revision % does not exist', NEW.supersedes_revision_id;
    END IF;
    IF prev_document <> NEW.document_id THEN
        RAISE EXCEPTION 'revision supersession must stay within one document';
    END IF;
    IF NEW.revision_number <> prev_number + 1 THEN
        RAISE EXCEPTION
            'revision_number must follow the superseded revision (expected %, got %)',
            prev_number + 1, NEW.revision_number;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS document_revisions_supersession_trg ON chronicle.document_revisions;
CREATE TRIGGER document_revisions_supersession_trg
    BEFORE INSERT OR UPDATE ON chronicle.document_revisions
    FOR EACH ROW EXECUTE FUNCTION chronicle.check_revision_supersession();

-- Revisions are immutable audit history: no UPDATE, no DELETE.
CREATE OR REPLACE FUNCTION chronicle.reject_revision_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'chronicle.document_revisions is immutable: replacement creates a new revision';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS document_revisions_no_update_trg ON chronicle.document_revisions;
CREATE TRIGGER document_revisions_no_update_trg
    BEFORE UPDATE OR DELETE ON chronicle.document_revisions
    FOR EACH ROW EXECUTE FUNCTION chronicle.reject_revision_mutation();

-- ---------------------------------------------------------------------------
-- Ingestion jobs (durable, restart-safe orchestration units)
-- ---------------------------------------------------------------------------
-- Job status vocabulary (frozen by C1-T1):
--   queued -> running -> {needs_review | failed | cancelled | completed}
--   needs_review -> running | failed | cancelled | completed
--   failed -> running (resume/retry) | cancelled
--   cancelled / completed are terminal.
-- Transition legality is enforced by the control-plane store (Python) and the
-- Rust domain model; the CHECK below freezes the vocabulary.

CREATE TABLE IF NOT EXISTS chronicle.ingestion_jobs (
    job_id uuid PRIMARY KEY CHECK (uuid_extract_version(job_id) = 7),
    document_id uuid NOT NULL REFERENCES chronicle.documents(document_id) ON DELETE RESTRICT,
    revision_id uuid NOT NULL REFERENCES chronicle.document_revisions(revision_id) ON DELETE RESTRICT,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'needs_review', 'failed', 'cancelled', 'completed')),
    priority integer NOT NULL DEFAULT 0,
    worker_id text NULL CHECK (worker_id IS NULL OR char_length(worker_id) BETWEEN 1 AND 200),
    lease_expires_at timestamptz NULL,
    heartbeat_at timestamptz NULL,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
    checkpoint jsonb NOT NULL DEFAULT '{}'::jsonb,
    error jsonb NULL,
    queued_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz NULL,
    finished_at timestamptz NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (lease_expires_at IS NULL OR worker_id IS NOT NULL),
    CHECK (finished_at IS NULL OR status IN ('failed', 'cancelled', 'completed'))
);

CREATE INDEX IF NOT EXISTS ingestion_jobs_claim_idx
    ON chronicle.ingestion_jobs(status, priority DESC, queued_at)
    WHERE status IN ('queued', 'running', 'failed');
CREATE INDEX IF NOT EXISTS ingestion_jobs_revision_idx
    ON chronicle.ingestion_jobs(revision_id);
CREATE INDEX IF NOT EXISTS ingestion_jobs_document_idx
    ON chronicle.ingestion_jobs(document_id);

-- A job is bound to exactly one immutable revision, and that revision must
-- belong to the job's document.
CREATE OR REPLACE FUNCTION chronicle.check_job_revision()
RETURNS trigger AS $$
DECLARE
    revision_document uuid;
BEGIN
    SELECT document_id INTO revision_document
    FROM chronicle.document_revisions
    WHERE revision_id = NEW.revision_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ingestion job revision % does not exist', NEW.revision_id;
    END IF;
    IF revision_document <> NEW.document_id THEN
        RAISE EXCEPTION 'ingestion job revision must belong to the job document';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS ingestion_jobs_revision_trg ON chronicle.ingestion_jobs;
CREATE TRIGGER ingestion_jobs_revision_trg
    BEFORE INSERT OR UPDATE OF document_id, revision_id ON chronicle.ingestion_jobs
    FOR EACH ROW EXECUTE FUNCTION chronicle.check_job_revision();

-- ---------------------------------------------------------------------------
-- Job stages (initial pipeline vocabulary, frozen by C1-T1)
-- ---------------------------------------------------------------------------
-- Stage vocabulary: prepare, structure, segment, extract, assemble, resolve,
-- publish, present.
-- Stage statuses: pending, running, needs_review, failed, skipped, completed.

CREATE TABLE IF NOT EXISTS chronicle.ingestion_job_stages (
    job_id uuid NOT NULL REFERENCES chronicle.ingestion_jobs(job_id) ON DELETE RESTRICT,
    stage text NOT NULL
        CHECK (stage IN ('prepare', 'structure', 'segment', 'extract', 'assemble', 'resolve', 'publish', 'present')),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'needs_review', 'failed', 'skipped', 'completed')),
    stage_order integer NOT NULL CHECK (stage_order >= 0),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    checkpoint jsonb NOT NULL DEFAULT '{}'::jsonb,
    error jsonb NULL,
    started_at timestamptz NULL,
    finished_at timestamptz NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, stage)
);

-- ---------------------------------------------------------------------------
-- Sections and chunks (processing units, not historical identity authority)
-- ---------------------------------------------------------------------------
-- Chunk identity is the stable (job, section, chunk_index) coordinate plus the
-- source byte offsets and content hash of the revision bytes it covers.
-- Semantic chunks never define historical truth; that authority stays with
-- the C0 staged -> resolution -> canonical path.

CREATE TABLE IF NOT EXISTS chronicle.ingestion_sections (
    section_id uuid PRIMARY KEY CHECK (uuid_extract_version(section_id) = 7),
    job_id uuid NOT NULL REFERENCES chronicle.ingestion_jobs(job_id) ON DELETE RESTRICT,
    revision_id uuid NOT NULL REFERENCES chronicle.document_revisions(revision_id) ON DELETE RESTRICT,
    section_index integer NOT NULL CHECK (section_index >= 0),
    section_kind text NOT NULL DEFAULT 'body'
        CHECK (section_kind IN ('front_matter', 'body', 'back_matter', 'heading', 'other')),
    title text NOT NULL DEFAULT '',
    source_start_offset bigint NOT NULL CHECK (source_start_offset >= 0),
    source_end_offset bigint NOT NULL CHECK (source_end_offset >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, section_index),
    CHECK (source_start_offset <= source_end_offset)
);

CREATE TABLE IF NOT EXISTS chronicle.ingestion_chunks (
    chunk_id uuid PRIMARY KEY CHECK (uuid_extract_version(chunk_id) = 7),
    job_id uuid NOT NULL REFERENCES chronicle.ingestion_jobs(job_id) ON DELETE RESTRICT,
    section_id uuid NOT NULL REFERENCES chronicle.ingestion_sections(section_id) ON DELETE RESTRICT,
    revision_id uuid NOT NULL REFERENCES chronicle.document_revisions(revision_id) ON DELETE RESTRICT,
    chunk_index integer NOT NULL CHECK (chunk_index >= 0),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'needs_review', 'failed', 'completed')),
    source_start_offset bigint NOT NULL CHECK (source_start_offset >= 0),
    source_end_offset bigint NOT NULL CHECK (source_end_offset >= 0),
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    coordinates jsonb NOT NULL DEFAULT '{}'::jsonb,
    retry_count integer NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    max_retries integer NOT NULL DEFAULT 3 CHECK (max_retries >= 0),
    next_retry_at timestamptz NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, section_id, chunk_index),
    CHECK (source_start_offset <= source_end_offset)
);

CREATE INDEX IF NOT EXISTS ingestion_chunks_job_status_idx
    ON chronicle.ingestion_chunks(job_id, status);
CREATE INDEX IF NOT EXISTS ingestion_chunks_revision_idx
    ON chronicle.ingestion_chunks(revision_id);

-- ---------------------------------------------------------------------------
-- Chunk runs (append-only attempt history; retries create new runs)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS chronicle.ingestion_chunk_runs (
    run_id uuid PRIMARY KEY CHECK (uuid_extract_version(run_id) = 7),
    chunk_id uuid NOT NULL REFERENCES chronicle.ingestion_chunks(chunk_id) ON DELETE RESTRICT,
    job_id uuid NOT NULL REFERENCES chronicle.ingestion_jobs(job_id) ON DELETE RESTRICT,
    attempt_number integer NOT NULL CHECK (attempt_number >= 1),
    status text NOT NULL DEFAULT 'started'
        CHECK (status IN ('started', 'succeeded', 'failed')),
    worker_id text NULL CHECK (worker_id IS NULL OR char_length(worker_id) BETWEEN 1 AND 200),
    checkpoint jsonb NOT NULL DEFAULT '{}'::jsonb,
    error jsonb NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz NULL,
    UNIQUE (chunk_id, attempt_number)
);

CREATE INDEX IF NOT EXISTS ingestion_chunk_runs_chunk_idx
    ON chronicle.ingestion_chunk_runs(chunk_id, attempt_number);

-- Chunk runs are append-only attempt history. A started run may complete
-- exactly once (succeeded/failed); finished runs are immutable and retries
-- always insert a new run row with the next attempt number.
CREATE OR REPLACE FUNCTION chronicle.check_chunk_run_completion()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'chronicle.ingestion_chunk_runs is append-only: retries create new runs';
    END IF;
    IF OLD.status <> 'started' THEN
        RAISE EXCEPTION 'finished chunk runs are immutable: retries create new runs';
    END IF;
    IF NEW.status NOT IN ('succeeded', 'failed') THEN
        RAISE EXCEPTION 'a started chunk run may only complete as succeeded/failed';
    END IF;
    IF NEW.run_id <> OLD.run_id OR NEW.chunk_id <> OLD.chunk_id
       OR NEW.job_id <> OLD.job_id OR NEW.attempt_number <> OLD.attempt_number THEN
        RAISE EXCEPTION 'chunk run identity is immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS ingestion_chunk_runs_no_mutation_trg ON chronicle.ingestion_chunk_runs;
CREATE TRIGGER ingestion_chunk_runs_no_mutation_trg
    BEFORE UPDATE OR DELETE ON chronicle.ingestion_chunk_runs
    FOR EACH ROW EXECUTE FUNCTION chronicle.check_chunk_run_completion();

-- ---------------------------------------------------------------------------
-- Review items (human/operator decisions over job output)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS chronicle.review_items (
    review_id uuid PRIMARY KEY CHECK (uuid_extract_version(review_id) = 7),
    job_id uuid NOT NULL REFERENCES chronicle.ingestion_jobs(job_id) ON DELETE RESTRICT,
    revision_id uuid NOT NULL REFERENCES chronicle.document_revisions(revision_id) ON DELETE RESTRICT,
    chunk_id uuid NULL REFERENCES chronicle.ingestion_chunks(chunk_id) ON DELETE RESTRICT,
    stage text NULL
        CHECK (stage IS NULL OR stage IN ('prepare', 'structure', 'segment', 'extract', 'assemble', 'resolve', 'publish', 'present')),
    kind text NOT NULL
        CHECK (kind IN ('segmentation', 'extraction', 'resolution_decision', 'assembly', 'publication', 'other')),
    status text NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'approved', 'rejected', 'superseded')),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    resolution jsonb NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz NULL,
    CHECK (resolved_at IS NULL OR status IN ('approved', 'rejected', 'superseded'))
);

CREATE INDEX IF NOT EXISTS review_items_job_status_idx
    ON chronicle.review_items(job_id, status);

-- ---------------------------------------------------------------------------
-- Ingestion outputs (assembled artifacts that feed the C0 path)
-- ---------------------------------------------------------------------------
-- Outputs reference assembled payloads by content hash. They do not replace
-- C0 staged / resolution / canonical rows; downstream publication reuses the
-- existing C0 import path unchanged.

CREATE TABLE IF NOT EXISTS chronicle.ingestion_outputs (
    output_id uuid PRIMARY KEY CHECK (uuid_extract_version(output_id) = 7),
    job_id uuid NOT NULL REFERENCES chronicle.ingestion_jobs(job_id) ON DELETE RESTRICT,
    revision_id uuid NOT NULL REFERENCES chronicle.document_revisions(revision_id) ON DELETE RESTRICT,
    output_kind text NOT NULL
        CHECK (output_kind IN ('staged_bundle', 'resolution_links', 'canonical_catalog', 'report', 'other')),
    artifact_sha256 text NOT NULL CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, output_kind, artifact_sha256)
);

CREATE INDEX IF NOT EXISTS ingestion_outputs_revision_idx
    ON chronicle.ingestion_outputs(revision_id);

CREATE OR REPLACE FUNCTION chronicle.reject_output_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'chronicle.ingestion_outputs is immutable: corrected output is a new row';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS ingestion_outputs_no_mutation_trg ON chronicle.ingestion_outputs;
CREATE TRIGGER ingestion_outputs_no_mutation_trg
    BEFORE UPDATE OR DELETE ON chronicle.ingestion_outputs
    FOR EACH ROW EXECUTE FUNCTION chronicle.reject_output_mutation();
