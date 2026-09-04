-- Chronicle C1-T5 section hierarchy (application-owned product persistence).
--
-- Strictly additive over 0003_chronicle_c1_documents.sql: it adds the
-- detected-structure fields to `chronicle.ingestion_sections` and never
-- alters C0 staged / resolution / canonical tables or any Loom
-- Runtime/World/Timeline/Work/Binding authority (Architecture Amendment
-- 0006, CHRONICLE_DATABASE_URL only).
--
-- Sections are ordered processing scopes with a detected hierarchy:
-- `kind` (volume/chapter/biography/treatise/heading/preamble/document,
-- or 'unknown' for rows predating structure detection), `depth` (nesting
-- level; volumes live at 0), and `parent_section_index` (the nearest
-- preceding section with a strictly smaller depth within the same job,
-- NULL at the top level). Chunks keep pointing at sections by
-- `section_id`; the hierarchy is recovered by reading the section rows
-- in `section_index` order, never from worker memory.

ALTER TABLE chronicle.ingestion_sections
    ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS depth integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS parent_section_index integer;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ingestion_sections_kind_valid'
          AND conrelid = 'chronicle.ingestion_sections'::regclass
    ) THEN
        ALTER TABLE chronicle.ingestion_sections
            ADD CONSTRAINT ingestion_sections_kind_valid CHECK (
                kind <> ''
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ingestion_sections_depth_valid'
          AND conrelid = 'chronicle.ingestion_sections'::regclass
    ) THEN
        ALTER TABLE chronicle.ingestion_sections
            ADD CONSTRAINT ingestion_sections_depth_valid CHECK (
                depth >= 0
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ingestion_sections_parent_valid'
          AND conrelid = 'chronicle.ingestion_sections'::regclass
    ) THEN
        ALTER TABLE chronicle.ingestion_sections
            ADD CONSTRAINT ingestion_sections_parent_valid CHECK (
                parent_section_index IS NULL
                OR (
                    parent_section_index >= 0
                    AND parent_section_index < section_index
                )
            );
    END IF;
END
$$;
