-- Chronicle C1-T3 document upload metadata (application-owned product persistence).
--
-- Strictly additive over 0002_chronicle_c1_control_plane.sql: it adds
-- per-revision upload metadata columns plus a tip-revision view, and never
-- alters C0 staged / resolution / canonical tables or any Loom
-- Runtime/World/Timeline/Work/Binding authority (Architecture Amendment
-- 0006, CHRONICLE_DATABASE_URL only).
--
-- Column defaults keep pre-C1-T3 revision rows (written by C1-T1 callers
-- that only knew sha/bytes/media-type) valid: filename/content_chars fall
-- back to neutral defaults, and storage_key is backfilled deterministically
-- from columns that already existed, before the NOT NULL / UNIQUE guards
-- are attached.

ALTER TABLE chronicle.document_revisions
    ADD COLUMN IF NOT EXISTS filename text NOT NULL DEFAULT 'upload.txt',
    ADD COLUMN IF NOT EXISTS content_chars bigint NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS language text,
    ADD COLUMN IF NOT EXISTS source_label text,
    ADD COLUMN IF NOT EXISTS storage_key text;

-- Deterministic backfill for rows predating this migration. New C1-T3
-- uploads always supply an explicit storage key; this only repairs history.
--
-- The backfill touches existing revision rows, but migration 0002 has
-- already installed the forbid_revision_mutation trigger that rejects
-- every application UPDATE/DELETE on this table. The trigger is therefore
-- parked for the single upgrade statement below and re-armed immediately
-- afterwards; ordinary writes stay forbidden before, during (outside this
-- migration transaction), and after the upgrade.
ALTER TABLE chronicle.document_revisions DISABLE TRIGGER forbid_revision_mutation;

UPDATE chronicle.document_revisions
SET storage_key = 'documents/' || document_id::text || '/' || revision_id::text || '.txt'
WHERE storage_key IS NULL;

ALTER TABLE chronicle.document_revisions ENABLE TRIGGER forbid_revision_mutation;

ALTER TABLE chronicle.document_revisions
    ALTER COLUMN storage_key SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'document_revisions_storage_key_unique'
          AND conrelid = 'chronicle.document_revisions'::regclass
    ) THEN
        ALTER TABLE chronicle.document_revisions
            ADD CONSTRAINT document_revisions_storage_key_unique UNIQUE (storage_key);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'document_revisions_filename_safe'
          AND conrelid = 'chronicle.document_revisions'::regclass
    ) THEN
        ALTER TABLE chronicle.document_revisions
            ADD CONSTRAINT document_revisions_filename_safe CHECK (
                filename <> ''
                AND filename NOT LIKE '%/%'
                AND filename NOT LIKE '%\%'
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'document_revisions_storage_key_safe'
          AND conrelid = 'chronicle.document_revisions'::regclass
    ) THEN
        ALTER TABLE chronicle.document_revisions
            ADD CONSTRAINT document_revisions_storage_key_safe CHECK (
                storage_key <> ''
                AND storage_key NOT LIKE '/%'
                AND storage_key NOT LIKE '%..%'
                AND storage_key NOT LIKE '%\%'
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'document_revisions_content_chars_valid'
          AND conrelid = 'chronicle.document_revisions'::regclass
    ) THEN
        ALTER TABLE chronicle.document_revisions
            ADD CONSTRAINT document_revisions_content_chars_valid CHECK (
                content_chars >= 0
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'document_revisions_language_valid'
          AND conrelid = 'chronicle.document_revisions'::regclass
    ) THEN
        ALTER TABLE chronicle.document_revisions
            ADD CONSTRAINT document_revisions_language_valid CHECK (
                language IS NULL OR language <> ''
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'document_revisions_source_label_valid'
          AND conrelid = 'chronicle.document_revisions'::regclass
    ) THEN
        ALTER TABLE chronicle.document_revisions
            ADD CONSTRAINT document_revisions_source_label_valid CHECK (
                source_label IS NULL OR source_label <> ''
            );
    END IF;
END
$$;

-- Active-revision lookup: the tip row (greatest revision_no) per document.
-- Earlier revisions are superseded by construction; revision rows stay
-- immutable (forbid_revision_mutation from 0002), so replacement never
-- overwrites or deletes history. Consumers must derive active/superseded
-- status from this view (or revision_no ordering), never from a mutable
-- status column on the revision itself.
CREATE OR REPLACE VIEW chronicle.document_current_revisions AS
SELECT DISTINCT ON (r.document_id) r.*
FROM chronicle.document_revisions r
ORDER BY r.document_id, r.revision_no DESC;
