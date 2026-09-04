-- Chronicle C1-T12 Reader Presentation projection (application-owned, derived).
--
-- This layer is deliberately NOT historical authority. Canonical identity,
-- staged Claims/evidence, Resolution Links and source records remain owned by
-- the existing C0/C1 knowledge tables. Reader Presentation is append-only,
-- zh-CN-only in C1, and every published atomic block must bind to one or more
-- existing staged Claims with evidence.

CREATE TABLE IF NOT EXISTS chronicle.reader_presentations (
    presentation_id uuid PRIMARY KEY,
    target_kind text NOT NULL CHECK (target_kind IN ('entity', 'event')),
    canonical_entity_id uuid REFERENCES chronicle.canonical_entities(canonical_id) ON DELETE RESTRICT,
    canonical_event_id uuid REFERENCES chronicle.canonical_events(canonical_id) ON DELETE RESTRICT,
    base_language text NOT NULL CHECK (base_language = 'zh-CN'),
    contract_version text NOT NULL CHECK (contract_version <> ''),
    presentation_version integer NOT NULL CHECK (presentation_version >= 1),
    status text NOT NULL CHECK (status IN ('published', 'rejected')),
    generator_version text NOT NULL CHECK (generator_version <> ''),
    model_version text NOT NULL CHECK (model_version <> ''),
    prompt_version text NOT NULL CHECK (prompt_version <> ''),
    input_fingerprint text NOT NULL CHECK (input_fingerprint ~ '^[0-9a-f]{64}$'),
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    origin_job_id uuid REFERENCES chronicle.ingestion_jobs(job_id) ON DELETE RESTRICT,
    supersedes_presentation_id uuid REFERENCES chronicle.reader_presentations(presentation_id) ON DELETE RESTRICT,
    generated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (target_kind = 'entity' AND canonical_entity_id IS NOT NULL AND canonical_event_id IS NULL)
        OR
        (target_kind = 'event' AND canonical_event_id IS NOT NULL AND canonical_entity_id IS NULL)
    ),
    CHECK (supersedes_presentation_id IS NULL OR supersedes_presentation_id <> presentation_id),
    UNIQUE (canonical_entity_id, presentation_version),
    UNIQUE (canonical_event_id, presentation_version)
);

CREATE INDEX IF NOT EXISTS reader_presentations_entity_idx
    ON chronicle.reader_presentations(canonical_entity_id, presentation_version DESC)
    WHERE canonical_entity_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS reader_presentations_event_idx
    ON chronicle.reader_presentations(canonical_event_id, presentation_version DESC)
    WHERE canonical_event_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS reader_presentations_fingerprint_idx
    ON chronicle.reader_presentations(input_fingerprint, content_sha256);

CREATE TABLE IF NOT EXISTS chronicle.reader_presentation_blocks (
    presentation_id uuid NOT NULL REFERENCES chronicle.reader_presentations(presentation_id) ON DELETE RESTRICT,
    block_index integer NOT NULL CHECK (block_index >= 0),
    block_id text NOT NULL CHECK (block_id <> ''),
    block_kind text NOT NULL CHECK (block_kind IN ('overview', 'sequence', 'outcome', 'source_notes', 'uncertainty')),
    epistemic_mode text NOT NULL CHECK (epistemic_mode IN ('fact_summary', 'source_report', 'uncertainty')),
    text text NOT NULL CHECK (btrim(text) <> ''),
    PRIMARY KEY (presentation_id, block_index),
    UNIQUE (presentation_id, block_id)
);

CREATE TABLE IF NOT EXISTS chronicle.reader_presentation_supports (
    presentation_id uuid NOT NULL,
    block_index integer NOT NULL,
    bundle_label text NOT NULL,
    claim_ref text NOT NULL,
    PRIMARY KEY (presentation_id, block_index, bundle_label, claim_ref),
    FOREIGN KEY (presentation_id, block_index)
        REFERENCES chronicle.reader_presentation_blocks(presentation_id, block_index) ON DELETE RESTRICT,
    FOREIGN KEY (bundle_label, claim_ref)
        REFERENCES chronicle.staged_claims(bundle_label, record_ref) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS reader_presentation_support_claim_idx
    ON chronicle.reader_presentation_supports(bundle_label, claim_ref);

-- Support is stronger than a bare foreign key: the Claim must carry direct
-- source evidence and must directly refer to a representation that belongs to
-- the presentation's canonical target. C1 v0 intentionally does not let a
-- presentation smuggle unrelated corpus facts in as "support".
CREATE OR REPLACE FUNCTION chronicle.validate_reader_presentation_support()
RETURNS trigger AS $$
DECLARE
    target record;
    claim jsonb;
    supported boolean := false;
BEGIN
    SELECT target_kind, canonical_entity_id, canonical_event_id
      INTO target
      FROM chronicle.reader_presentations
     WHERE presentation_id = NEW.presentation_id;

    SELECT payload INTO claim
      FROM chronicle.staged_claims
     WHERE bundle_label = NEW.bundle_label AND record_ref = NEW.claim_ref;

    IF claim IS NULL THEN
        RAISE EXCEPTION 'reader presentation support Claim %.% does not exist', NEW.bundle_label, NEW.claim_ref;
    END IF;
    IF jsonb_typeof(claim->'evidence') <> 'object'
       OR COALESCE(btrim(claim->'evidence'->>'text'), '') = ''
       OR COALESCE(btrim(claim->'evidence'->>'source_ref'), '') = '' THEN
        RAISE EXCEPTION 'reader presentation support Claim %.% lacks direct evidence text/source_ref', NEW.bundle_label, NEW.claim_ref;
    END IF;

    IF target.target_kind = 'entity' THEN
        SELECT EXISTS (
            SELECT 1
              FROM chronicle.canonical_entity_representations r
             WHERE r.canonical_id = target.canonical_entity_id
               AND r.bundle_label = NEW.bundle_label
               AND (
                    (claim->'subject'->>'kind' = 'entity_ref' AND claim->'subject'->>'ref' = r.record_ref)
                 OR (claim->'object'->>'kind' = 'entity_ref' AND claim->'object'->>'ref' = r.record_ref)
               )
        ) INTO supported;
    ELSE
        SELECT EXISTS (
            SELECT 1
              FROM chronicle.canonical_event_representations r
             WHERE r.canonical_id = target.canonical_event_id
               AND r.bundle_label = NEW.bundle_label
               AND (
                    (claim->'subject'->>'kind' = 'event_ref' AND claim->'subject'->>'ref' = r.record_ref)
                 OR (claim->'object'->>'kind' = 'event_ref' AND claim->'object'->>'ref' = r.record_ref)
               )
        ) INTO supported;
    END IF;

    IF NOT supported THEN
        RAISE EXCEPTION 'reader presentation support Claim %.% is outside canonical target scope', NEW.bundle_label, NEW.claim_ref;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS validate_reader_presentation_support ON chronicle.reader_presentation_supports;
CREATE TRIGGER validate_reader_presentation_support
    BEFORE INSERT OR UPDATE ON chronicle.reader_presentation_supports
    FOR EACH ROW EXECUTE FUNCTION chronicle.validate_reader_presentation_support();

-- Reader projections are immutable audit artifacts. Regeneration appends a new
-- presentation_version and points `supersedes_presentation_id` at the previous
-- version; it never edits old prose or support bindings in place.
CREATE OR REPLACE FUNCTION chronicle.forbid_reader_presentation_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Chronicle Reader Presentation rows are append-only; regenerate a new version instead';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS forbid_reader_presentation_mutation ON chronicle.reader_presentations;
CREATE TRIGGER forbid_reader_presentation_mutation
    BEFORE UPDATE OR DELETE ON chronicle.reader_presentations
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_reader_presentation_mutation();

DROP TRIGGER IF EXISTS forbid_reader_presentation_block_mutation ON chronicle.reader_presentation_blocks;
CREATE TRIGGER forbid_reader_presentation_block_mutation
    BEFORE UPDATE OR DELETE ON chronicle.reader_presentation_blocks
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_reader_presentation_mutation();

DROP TRIGGER IF EXISTS forbid_reader_presentation_support_mutation ON chronicle.reader_presentation_supports;
CREATE TRIGGER forbid_reader_presentation_support_mutation
    BEFORE UPDATE OR DELETE ON chronicle.reader_presentation_supports
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_reader_presentation_mutation();
