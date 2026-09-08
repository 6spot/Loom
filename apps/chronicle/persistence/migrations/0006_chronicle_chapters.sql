-- Chronicle C2-R1-T04 chapter artifact + publication store (application-owned).
--
-- Strictly additive over 0005_chronicle_c1_reader_presentations.sql: it
-- creates the chapter tables, tightens the resolution same-bundle / self-ref
-- guards, and adds the canonical publication sequence. It never alters Loom
-- Runtime/World/Timeline/Work/Binding authority (Architecture Amendment
-- 0006, CHRONICLE_DATABASE_URL only), never weakens the 0005 Reader
-- Presentation entity/event + Claim-only support constraint, and never
-- copies staged entity tables.
--
-- Authority: chapter-production.md sections 5/7. chapter_store.py holds the
-- new chapter tables; catalogs stay owned by canonical_store.py. The
-- publication_sequence column is structure only here: the unified lock and
-- write path belong to T13, which also migrates latest-catalog reads off
-- imported_at. Cross-chapter candidate validation belongs to T08; this
-- migration only enforces the version/scope envelope and the self-ref ban.
--
-- Conventions: artifact_sha256 PK, job/revision/chapter/chunk/producing-run
-- bindings, request_fingerprint, immutable JSONB payload. The complete joint
-- product (translation + extraction + record_sources) is accepted only
-- through the chapter_store accepted-write entry; partial products are never
-- persisted. Original run/source references are retained on every row.

-- ---------------------------------------------------------------------------
-- chapter_artifacts: one immutable accepted joint product per (job, chapter).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chronicle.chapter_artifacts (
    artifact_sha256 text PRIMARY KEY CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    job_id uuid NOT NULL REFERENCES chronicle.ingestion_jobs(job_id) ON DELETE RESTRICT,
    revision_id uuid NOT NULL REFERENCES chronicle.document_revisions(revision_id) ON DELETE RESTRICT,
    document_id uuid NOT NULL REFERENCES chronicle.documents(document_id) ON DELETE RESTRICT,
    chapter_id text NOT NULL CHECK (chapter_id <> ''),
    chapter_index integer NOT NULL CHECK (chapter_index >= 0),
    chunk_id uuid NOT NULL REFERENCES chronicle.ingestion_chunks(chunk_id) ON DELETE RESTRICT,
    producing_run_id uuid NOT NULL REFERENCES chronicle.ingestion_chunk_runs(run_id) ON DELETE RESTRICT,
    request_fingerprint text NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
    candidate_sha256 text NOT NULL CHECK (candidate_sha256 ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, chapter_id),
    UNIQUE (job_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS chapter_artifacts_job_idx
    ON chronicle.chapter_artifacts(job_id);
CREATE INDEX IF NOT EXISTS chapter_artifacts_revision_idx
    ON chronicle.chapter_artifacts(revision_id);

-- ---------------------------------------------------------------------------
-- chapter_publications: one immutable public reading version per chapter.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chronicle.chapter_publications (
    publication_id uuid PRIMARY KEY CHECK (uuid_extract_version(publication_id) = 7),
    artifact_sha256 text NOT NULL REFERENCES chronicle.chapter_artifacts(artifact_sha256) ON DELETE RESTRICT,
    catalog_sha256 text NOT NULL CHECK (catalog_sha256 ~ '^[0-9a-f]{64}$'),
    assembled_bundle_sha256 text NOT NULL CHECK (assembled_bundle_sha256 ~ '^[0-9a-f]{64}$'),
    document_id uuid NOT NULL REFERENCES chronicle.documents(document_id) ON DELETE RESTRICT,
    revision_id uuid NOT NULL REFERENCES chronicle.document_revisions(revision_id) ON DELETE RESTRICT,
    job_id uuid NOT NULL REFERENCES chronicle.ingestion_jobs(job_id) ON DELETE RESTRICT,
    chapter_id text NOT NULL CHECK (chapter_id <> ''),
    payload jsonb NOT NULL,
    published_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (artifact_sha256, catalog_sha256, assembled_bundle_sha256)
);

CREATE INDEX IF NOT EXISTS chapter_publications_job_idx
    ON chronicle.chapter_publications(job_id);
CREATE INDEX IF NOT EXISTS chapter_publications_revision_idx
    ON chronicle.chapter_publications(revision_id);
CREATE INDEX IF NOT EXISTS chapter_publications_catalog_idx
    ON chronicle.chapter_publications(catalog_sha256);

-- ---------------------------------------------------------------------------
-- Immutability: accepted chapters and publications are append-only audit
-- history. Recovery replays the same artifact/publication idempotently; it
-- never edits rows in place.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION chronicle.forbid_chapter_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Chronicle chapter rows are append-only; replay the accepted artifact instead';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS forbid_chapter_artifact_mutation ON chronicle.chapter_artifacts;
CREATE TRIGGER forbid_chapter_artifact_mutation
    BEFORE UPDATE OR DELETE ON chronicle.chapter_artifacts
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_chapter_mutation();

DROP TRIGGER IF EXISTS forbid_chapter_publication_mutation ON chronicle.chapter_publications;
CREATE TRIGGER forbid_chapter_publication_mutation
    BEFORE UPDATE OR DELETE ON chronicle.chapter_publications
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_chapter_mutation();

-- ---------------------------------------------------------------------------
-- Binding backstops (D-1 style): every chapter artifact resolves to exactly
-- one job/revision/document/chunk/producing-run. Foreign keys alone cannot
-- express "same job" across parent links, so triggers reject cross-job
-- bindings at the database, independent of worker code. The store pre-checks
-- the same invariants; these triggers are the second fence.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION chronicle.enforce_chapter_artifact_binding()
RETURNS trigger AS $$
DECLARE
    job_revision uuid;
    revision_document uuid;
    chunk_job uuid;
    run_chunk uuid;
BEGIN
    SELECT revision_id INTO job_revision
      FROM chronicle.ingestion_jobs WHERE job_id = NEW.job_id;
    IF job_revision IS DISTINCT FROM NEW.revision_id THEN
        RAISE EXCEPTION 'chronicle.chapter_artifacts revision % does not match revision % of job %', NEW.revision_id, job_revision, NEW.job_id;
    END IF;
    SELECT document_id INTO revision_document
      FROM chronicle.document_revisions WHERE revision_id = NEW.revision_id;
    IF revision_document IS DISTINCT FROM NEW.document_id THEN
        RAISE EXCEPTION 'chronicle.chapter_artifacts document % does not match document % of revision %', NEW.document_id, revision_document, NEW.revision_id;
    END IF;
    SELECT job_id INTO chunk_job
      FROM chronicle.ingestion_chunks WHERE chunk_id = NEW.chunk_id;
    IF chunk_job IS DISTINCT FROM NEW.job_id THEN
        RAISE EXCEPTION 'chronicle.chapter_artifacts chunk % belongs to a different job than chapter job %', NEW.chunk_id, NEW.job_id;
    END IF;
    SELECT chunk_id INTO run_chunk
      FROM chronicle.ingestion_chunk_runs WHERE run_id = NEW.producing_run_id;
    IF run_chunk IS DISTINCT FROM NEW.chunk_id THEN
        RAISE EXCEPTION 'chronicle.chapter_artifacts producing run % belongs to a different chunk than chapter chunk %', NEW.producing_run_id, NEW.chunk_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_chapter_artifact_binding ON chronicle.chapter_artifacts;
CREATE TRIGGER enforce_chapter_artifact_binding
    BEFORE INSERT ON chronicle.chapter_artifacts
    FOR EACH ROW EXECUTE FUNCTION chronicle.enforce_chapter_artifact_binding();

CREATE OR REPLACE FUNCTION chronicle.enforce_chapter_publication_binding()
RETURNS trigger AS $$
DECLARE
    artifact record;
BEGIN
    SELECT job_id, revision_id, document_id, chapter_id
      INTO artifact
      FROM chronicle.chapter_artifacts WHERE artifact_sha256 = NEW.artifact_sha256;
    IF artifact IS NULL THEN
        RAISE EXCEPTION 'chronicle.chapter_publications artifact % is not persisted', NEW.artifact_sha256;
    END IF;
    IF artifact.job_id IS DISTINCT FROM NEW.job_id
       OR artifact.revision_id IS DISTINCT FROM NEW.revision_id
       OR artifact.document_id IS DISTINCT FROM NEW.document_id
       OR artifact.chapter_id IS DISTINCT FROM NEW.chapter_id THEN
        RAISE EXCEPTION 'chronicle.chapter_publications job/revision/document/chapter does not match artifact %', NEW.artifact_sha256;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_chapter_publication_binding ON chronicle.chapter_publications;
CREATE TRIGGER enforce_chapter_publication_binding
    BEFORE INSERT ON chronicle.chapter_publications
    FOR EACH ROW EXECUTE FUNCTION chronicle.enforce_chapter_publication_binding();

-- ---------------------------------------------------------------------------
-- Resolution envelope: same-bundle artifacts are allowed only for validated
-- v0.2 within_revision documents. v0.1 and cross_source keep the original
-- distinct-bundle requirement; existing foreign keys and decision enums are
-- untouched. Whether a same-bundle candidate spans different chapters is
-- business validation owned by T08, never auto-derived here.
-- ---------------------------------------------------------------------------
ALTER TABLE chronicle.resolution_artifacts
    ADD COLUMN IF NOT EXISTS scope text;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'resolution_artifacts_scope_valid'
          AND conrelid = 'chronicle.resolution_artifacts'::regclass
    ) THEN
        ALTER TABLE chronicle.resolution_artifacts
            ADD CONSTRAINT resolution_artifacts_scope_valid CHECK (
                scope IS NULL OR scope IN ('within_revision', 'cross_source')
            );
    END IF;
END
$$;

-- Replace the original distinct-bundle CHECK with the scoped envelope. The
-- original inline CHECK carries an auto-generated name, so drop whichever
-- check constrains the bundle pair before installing the named successor.
DO $$
DECLARE
    constraint_name text;
BEGIN
    SELECT c.conname INTO constraint_name
      FROM pg_constraint c
     WHERE c.conrelid = 'chronicle.resolution_artifacts'::regclass
       AND c.contype = 'c'
       AND c.conname <> 'resolution_artifacts_bundle_scope_valid'
       AND pg_get_constraintdef(c.oid) LIKE '%left_bundle_label%right_bundle_label%'
     LIMIT 1;
    IF constraint_name IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE chronicle.resolution_artifacts DROP CONSTRAINT %I',
            constraint_name
        );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'resolution_artifacts_bundle_scope_valid'
          AND conrelid = 'chronicle.resolution_artifacts'::regclass
    ) THEN
        ALTER TABLE chronicle.resolution_artifacts
            ADD CONSTRAINT resolution_artifacts_bundle_scope_valid CHECK (
                left_bundle_label <> right_bundle_label
                OR (
                    schema_name = 'chronicle.resolution-links'
                    AND schema_version = '0.2'
                    AND scope = 'within_revision'
                )
            );
    END IF;
END
$$;

-- Self-links are never reviewable identity: the two ends of one Entity/Event
-- link must not be the same (bundle, ref). Foreign keys and decision enums
-- are unchanged.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'resolution_entity_links_no_self_ref'
          AND conrelid = 'chronicle.resolution_entity_links'::regclass
    ) THEN
        ALTER TABLE chronicle.resolution_entity_links
            ADD CONSTRAINT resolution_entity_links_no_self_ref CHECK (
                (left_bundle_label, left_record_ref)
                <> (right_bundle_label, right_record_ref)
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'resolution_event_links_no_self_ref'
          AND conrelid = 'chronicle.resolution_event_links'::regclass
    ) THEN
        ALTER TABLE chronicle.resolution_event_links
            ADD CONSTRAINT resolution_event_links_no_self_ref CHECK (
                (left_bundle_label, left_record_ref)
                <> (right_bundle_label, right_record_ref)
            );
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- Canonical publication order: unique increasing sequence for latest-catalog
-- reads. Structure only in this migration: the unified advisory lock, the
-- locked write path, and the read-path migration off imported_at belong to
-- T13 and must reuse this column, not a second sequence.
-- ---------------------------------------------------------------------------
ALTER TABLE chronicle.canonical_catalogs
    ADD COLUMN IF NOT EXISTS publication_sequence bigint GENERATED ALWAYS AS IDENTITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'canonical_catalogs_publication_sequence_unique'
          AND conrelid = 'chronicle.canonical_catalogs'::regclass
    ) THEN
        ALTER TABLE chronicle.canonical_catalogs
            ADD CONSTRAINT canonical_catalogs_publication_sequence_unique
            UNIQUE (publication_sequence);
    END IF;
END
$$;
