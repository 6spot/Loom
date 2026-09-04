-- Chronicle C1-T1 ingestion control-plane contract (application-owned product persistence).
--
-- This migration is strictly additive: it creates new `chronicle.*` control-plane
-- tables and never alters the C0 staged / resolution / canonical tables from
-- `0001_chronicle_v0.sql`. C1 ingestion outputs feed the existing C0
-- staged/resolution/canonical path after assembly; they do not bypass it.
--
-- Authority: Chronicle application-owned persistence behind CHRONICLE_DATABASE_URL
-- (Architecture Amendment 0006). No Loom Runtime/World/Timeline/Work/Binding
-- authority is created, moved, or exposed here.

-- Documents group immutable source revisions of one complete historical document.
CREATE TABLE IF NOT EXISTS chronicle.documents (
    document_id uuid PRIMARY KEY,
    title text NOT NULL CHECK (title <> ''),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Immutable source revisions. Replacing a source inserts a new revision row that
-- supersedes the previous tip; existing rows are never updated or deleted
-- (enforced by chronicle.forbid_revision_mutation below). The current revision
-- of a document is the row with the greatest revision_no.
CREATE TABLE IF NOT EXISTS chronicle.document_revisions (
    revision_id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES chronicle.documents(document_id) ON DELETE RESTRICT,
    revision_no integer NOT NULL CHECK (revision_no >= 1),
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    source_bytes bigint NOT NULL CHECK (source_bytes >= 0),
    source_media_type text NOT NULL CHECK (source_media_type <> ''),
    supersedes_revision_id uuid REFERENCES chronicle.document_revisions(revision_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, revision_no),
    CHECK (supersedes_revision_id IS NULL OR supersedes_revision_id <> revision_id)
);

CREATE INDEX IF NOT EXISTS document_revisions_document_idx
    ON chronicle.document_revisions(document_id, revision_no);

-- Immutability guard: revision rows are append-only audit history.
CREATE OR REPLACE FUNCTION chronicle.forbid_revision_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'chronicle.document_revisions is immutable (C1-T1): replacing a source must insert a new revision, never UPDATE or DELETE %', OLD.revision_id;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS forbid_revision_mutation ON chronicle.document_revisions;
CREATE TRIGGER forbid_revision_mutation
    BEFORE UPDATE OR DELETE ON chronicle.document_revisions
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_revision_mutation();

-- Ingestion jobs: one durable, restart-safe workflow per immutable revision.
-- Status vocabulary (frozen by C1-T1): queued, running, needs_review, failed,
-- cancelled, completed. Lease columns are provider-neutral worker coordination
-- fields; they do not freeze a specific worker implementation.
CREATE TABLE IF NOT EXISTS chronicle.ingestion_jobs (
    job_id uuid PRIMARY KEY,
    revision_id uuid NOT NULL REFERENCES chronicle.document_revisions(revision_id) ON DELETE RESTRICT,
    status text NOT NULL CHECK (status IN ('queued', 'running', 'needs_review', 'failed', 'cancelled', 'completed')),
    attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
    lease_owner text,
    lease_expires_at timestamptz,
    checkpoint jsonb NOT NULL DEFAULT '{}',
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ingestion_jobs_status_idx
    ON chronicle.ingestion_jobs(status);
CREATE INDEX IF NOT EXISTS ingestion_jobs_revision_idx
    ON chronicle.ingestion_jobs(revision_id);

-- Pipeline stages of a job. Initial C1-T1 vocabulary:
-- prepare, structure, segment, extract, assemble, resolve, publish, present.
-- Stage statuses: pending, running, needs_review, failed, skipped, completed.
CREATE TABLE IF NOT EXISTS chronicle.ingestion_job_stages (
    job_id uuid NOT NULL REFERENCES chronicle.ingestion_jobs(job_id) ON DELETE RESTRICT,
    stage text NOT NULL CHECK (stage IN ('prepare', 'structure', 'segment', 'extract', 'assemble', 'resolve', 'publish', 'present')),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'needs_review', 'failed', 'skipped', 'completed')),
    attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    checkpoint jsonb NOT NULL DEFAULT '{}',
    error text,
    started_at timestamptz,
    finished_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, stage)
);

-- Sections partition one job's revision into ordered processing scopes
-- (e.g. detected book structure units). Sections are coordinates, not identity.
CREATE TABLE IF NOT EXISTS chronicle.ingestion_sections (
    section_id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES chronicle.ingestion_jobs(job_id) ON DELETE RESTRICT,
    section_index integer NOT NULL CHECK (section_index >= 0),
    label text NOT NULL CHECK (label <> ''),
    source_start bigint NOT NULL CHECK (source_start >= 0),
    source_end bigint NOT NULL CHECK (source_end >= source_start),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, section_index)
);

-- Chunks are model-processing units addressed by stable
-- revision/job/section coordinates plus source offsets and hashes.
-- Chunks never become historical identity/truth boundaries.
CREATE TABLE IF NOT EXISTS chronicle.ingestion_chunks (
    chunk_id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES chronicle.ingestion_jobs(job_id) ON DELETE RESTRICT,
    section_id uuid REFERENCES chronicle.ingestion_sections(section_id) ON DELETE RESTRICT,
    chunk_index integer NOT NULL CHECK (chunk_index >= 0),
    source_start bigint NOT NULL CHECK (source_start >= 0),
    source_end bigint NOT NULL CHECK (source_end >= source_start),
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'needs_review', 'failed', 'completed')),
    attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
    checkpoint jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS ingestion_chunks_job_section_idx
    ON chronicle.ingestion_chunks(job_id, section_id);
CREATE INDEX IF NOT EXISTS ingestion_chunks_status_idx
    ON chronicle.ingestion_chunks(status);

-- Append-only per-attempt execution history for a chunk. Retries insert a new
-- run row with attempt = chunk.attempt + 1; run rows are never mutated.
CREATE TABLE IF NOT EXISTS chronicle.ingestion_chunk_runs (
    run_id uuid PRIMARY KEY,
    chunk_id uuid NOT NULL REFERENCES chronicle.ingestion_chunks(chunk_id) ON DELETE RESTRICT,
    attempt integer NOT NULL CHECK (attempt >= 1),
    status text NOT NULL CHECK (status IN ('running', 'failed', 'completed')),
    worker text NOT NULL CHECK (worker <> ''),
    checkpoint jsonb NOT NULL DEFAULT '{}',
    error text,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    UNIQUE (chunk_id, attempt)
);

-- Human review gates. A job enters needs_review while an open item exists;
-- resolving every open item lets the worker resume the job.
CREATE TABLE IF NOT EXISTS chronicle.review_items (
    review_id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES chronicle.ingestion_jobs(job_id) ON DELETE RESTRICT,
    chunk_id uuid REFERENCES chronicle.ingestion_chunks(chunk_id) ON DELETE RESTRICT,
    kind text NOT NULL CHECK (kind IN ('chunk_failure', 'stage_gate', 'quality_flag')),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'dismissed')),
    payload jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz
);

CREATE INDEX IF NOT EXISTS review_items_job_status_idx
    ON chronicle.review_items(job_id, status);

-- Assembled ingestion outputs. Outputs reference the exact immutable revision
-- and producing job; downstream C0 staged/resolution/canonical imports remain
-- the historical-knowledge path and are never bypassed by this table.
CREATE TABLE IF NOT EXISTS chronicle.ingestion_outputs (
    output_id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES chronicle.ingestion_jobs(job_id) ON DELETE RESTRICT,
    revision_id uuid NOT NULL REFERENCES chronicle.document_revisions(revision_id) ON DELETE RESTRICT,
    artifact_type text NOT NULL CHECK (artifact_type <> ''),
    artifact_sha256 text NOT NULL CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, artifact_type, artifact_sha256)
);

CREATE INDEX IF NOT EXISTS ingestion_outputs_revision_idx
    ON chronicle.ingestion_outputs(revision_id);

-- Relationship invariants (D-1): every chunk/run/review/output row must
-- resolve to exactly one immutable revision through its job. Foreign keys
-- alone cannot express "same job" across two parent links, so triggers
-- reject cross-job bindings at the database, independent of worker code.
CREATE OR REPLACE FUNCTION chronicle.enforce_chunk_section_job()
RETURNS trigger AS $$
DECLARE
    section_job uuid;
BEGIN
    IF NEW.section_id IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT job_id INTO section_job
    FROM chronicle.ingestion_sections WHERE section_id = NEW.section_id;
    IF section_job IS DISTINCT FROM NEW.job_id THEN
        RAISE EXCEPTION 'chronicle.ingestion_chunks section % belongs to a different job than chunk job %', NEW.section_id, NEW.job_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_chunk_section_job ON chronicle.ingestion_chunks;
CREATE TRIGGER enforce_chunk_section_job
    BEFORE INSERT OR UPDATE ON chronicle.ingestion_chunks
    FOR EACH ROW EXECUTE FUNCTION chronicle.enforce_chunk_section_job();

CREATE OR REPLACE FUNCTION chronicle.enforce_review_chunk_job()
RETURNS trigger AS $$
DECLARE
    chunk_job uuid;
BEGIN
    IF NEW.chunk_id IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT job_id INTO chunk_job
    FROM chronicle.ingestion_chunks WHERE chunk_id = NEW.chunk_id;
    IF chunk_job IS DISTINCT FROM NEW.job_id THEN
        RAISE EXCEPTION 'chronicle.review_items chunk % belongs to a different job than review job %', NEW.chunk_id, NEW.job_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_review_chunk_job ON chronicle.review_items;
CREATE TRIGGER enforce_review_chunk_job
    BEFORE INSERT OR UPDATE ON chronicle.review_items
    FOR EACH ROW EXECUTE FUNCTION chronicle.enforce_review_chunk_job();

CREATE OR REPLACE FUNCTION chronicle.enforce_output_revision_job()
RETURNS trigger AS $$
DECLARE
    job_revision uuid;
BEGIN
    SELECT revision_id INTO job_revision
    FROM chronicle.ingestion_jobs WHERE job_id = NEW.job_id;
    IF job_revision IS DISTINCT FROM NEW.revision_id THEN
        RAISE EXCEPTION 'chronicle.ingestion_outputs revision % does not match revision % of job %', NEW.revision_id, job_revision, NEW.job_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_output_revision_job ON chronicle.ingestion_outputs;
CREATE TRIGGER enforce_output_revision_job
    BEFORE INSERT OR UPDATE ON chronicle.ingestion_outputs
    FOR EACH ROW EXECUTE FUNCTION chronicle.enforce_output_revision_job();
