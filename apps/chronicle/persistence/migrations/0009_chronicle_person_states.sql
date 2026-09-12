-- Chronicle C2-R3-T05 person-state assessment / projection / disagreement index
-- (application-owned product persistence).
--
-- Strictly additive over 0008_chronicle_historical_narratives.sql: it creates
-- the third-round person-state tables fixed by
-- apps/chronicle/docs/person-state-reading.md section 6 and adds no column,
-- constraint or trigger to any existing table. It never copies body text,
-- full translations, Entity/Claim tables, canonical entities or the job state
-- machine; every row points at the existing publication / stream / unit /
-- catalog / assessment identity. It never touches Loom Runtime/World/Timeline
-- authority and only ever uses CHRONICLE_DATABASE_URL (Architecture Amendment
-- 0006). It does not weaken the 0006 chapter guards or the 0007 reading
-- immutability and snapshot-membership fences.
--
-- Authority: person-state-reading.md sections 5-7, third-round task T05.
-- person_state_store.py owns these tables; the persist_* entries write inside
-- the caller's already-open transaction (T08's unique publication transaction)
-- and the list_* entries are SELECT-only bounded keyset reads for T09. The
-- tables are append-only: a corrected state is a new stream publication, never
-- an in-place edit.
--
-- Conventions: SHA-256 checksum columns are lowercase hex; compiled item ids
-- use the T01 contract's `psi_...`, disagreement ids use `psd_...`; UUID
-- publication identity is UUIDv7. Composite foreign keys stop cross-stream /
-- cross-unit / cross-person splices, and binding triggers close the gaps that
-- array columns cannot express (nonexistent assessment, chapter publication
-- outside the stream's own snapshot).

-- ---------------------------------------------------------------------------
-- person_state_assessments: one immutable reviewed assessment artifact per
-- frozen plan. The exact candidate decisions and audit references live in the
-- payload; the original accepted chapter artifact is never touched.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chronicle.person_state_assessments (
    assessment_sha text PRIMARY KEY CHECK (assessment_sha ~ '^[0-9a-f]{64}$'),
    plan_fingerprint text NOT NULL CHECK (plan_fingerprint ~ '^[0-9a-f]{64}$'),
    base_catalog_sha text NOT NULL
        REFERENCES chronicle.canonical_catalogs(artifact_sha256) ON DELETE RESTRICT,
    compiler_version text NOT NULL CHECK (compiler_version <> ''),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (plan_fingerprint)
);

-- ---------------------------------------------------------------------------
-- person_state_manifests: one immutable compiled state manifest per reading
-- stream. It records the stream, its chapter publications, the assessment
-- artifacts that fed the compile, the compiler version and the manifest hash.
-- `payload` is the T04/compiler manifest object; the `manifest_sha` primary
-- key is the hash of the complete normalized compiled input.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chronicle.person_state_manifests (
    manifest_sha text PRIMARY KEY CHECK (manifest_sha ~ '^[0-9a-f]{64}$'),
    stream_id uuid NOT NULL UNIQUE
        REFERENCES chronicle.reading_streams(stream_id) ON DELETE RESTRICT,
    revision_id uuid NOT NULL
        REFERENCES chronicle.document_revisions(revision_id) ON DELETE RESTRICT,
    origin_catalog_sha text NOT NULL
        REFERENCES chronicle.canonical_catalogs(artifact_sha256) ON DELETE RESTRICT,
    compiler_version text NOT NULL CHECK (compiler_version <> ''),
    assessment_hashes text[] NOT NULL,
    chapter_publication_ids uuid[] NOT NULL
        CHECK (cardinality(chapter_publication_ids) > 0),
    unit_phases jsonb NOT NULL,
    manifest jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (manifest_sha, stream_id)
);

-- ---------------------------------------------------------------------------
-- person_state_unit_people: the bounded per-unit person summary index. One row
-- per (stream, unit, person) with the phase grouping, certainty/reasons and the
-- preview items used to answer `list_unit_people` without scanning items.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chronicle.person_state_unit_people (
    manifest_sha text NOT NULL,
    stream_id uuid NOT NULL,
    unit_id text NOT NULL CHECK (unit_id <> ''),
    person_id text NOT NULL CHECK (person_id <> ''),
    unit_ordinal integer NOT NULL CHECK (unit_ordinal >= 0),
    name text NOT NULL CHECK (name <> ''),
    importance text NOT NULL CHECK (importance IN ('primary', 'other')),
    importance_rank smallint NOT NULL CHECK (importance_rank IN (0, 1)),
    phase_mode text NOT NULL CHECK (
        phase_mode IN ('single', 'process', 'ambiguous', 'unknown')
    ),
    certainty text NOT NULL CHECK (certainty IN ('clear', 'uncertain')),
    reason_codes text[] NOT NULL,
    phases jsonb NOT NULL,
    identity_count integer NOT NULL CHECK (identity_count >= 0),
    change_count integer NOT NULL CHECK (change_count >= 0),
    preview_identities jsonb NOT NULL,
    preview_changes jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (manifest_sha, stream_id, unit_id, person_id),
    FOREIGN KEY (manifest_sha, stream_id)
        REFERENCES chronicle.person_state_manifests(manifest_sha, stream_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (stream_id, unit_id)
        REFERENCES chronicle.reading_units(stream_id, unit_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS person_state_unit_people_page_idx
    ON chronicle.person_state_unit_people(
        stream_id, unit_id, importance_rank, person_id
    );

-- ---------------------------------------------------------------------------
-- person_state_items: the full compiled identity / change entries backing one
-- unit person row. Identity rows carry `current`; change rows carry the
-- operation and from/to phases. `item_ordinal` fixes stable pagination order.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chronicle.person_state_items (
    manifest_sha text NOT NULL,
    stream_id uuid NOT NULL,
    unit_id text NOT NULL,
    person_id text NOT NULL,
    item_kind text NOT NULL CHECK (item_kind IN ('identity', 'change')),
    item_id text NOT NULL CHECK (item_id ~ '^psi_[0-9a-f]{24}$'),
    dimension text NOT NULL CHECK (dimension IN ('office', 'title', 'affiliation')),
    value text,
    relation text CHECK (relation IS NULL OR relation IN ('serves', 'attached_to')),
    target text,
    target_id text,
    qualification text NOT NULL CHECK (
        qualification IN (
            'ordinary', 'recommendation', 'self_designation', 'posthumous', 'reported'
        )
    ),
    certainty text NOT NULL CHECK (certainty IN ('clear', 'uncertain')),
    reason_codes text[] NOT NULL,
    reason_text text NOT NULL,
    phase_ids text[] NOT NULL,
    current boolean,
    operation text CHECK (operation IS NULL OR operation IN ('start', 'end', 'attest')),
    from_phase_id text,
    to_phase_id text,
    source_facts jsonb NOT NULL,
    evidence_count integer NOT NULL CHECK (evidence_count >= 0),
    item_ordinal integer NOT NULL CHECK (item_ordinal >= 0),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (manifest_sha, stream_id, unit_id, item_id),
    FOREIGN KEY (manifest_sha, stream_id, unit_id, person_id)
        REFERENCES chronicle.person_state_unit_people(
            manifest_sha, stream_id, unit_id, person_id
        ) ON DELETE RESTRICT,
    CHECK (item_kind = 'identity' OR (current IS NULL)),
    CHECK (item_kind = 'change' OR (operation IS NULL AND to_phase_id IS NULL))
);

CREATE INDEX IF NOT EXISTS person_state_items_page_idx
    ON chronicle.person_state_items(
        stream_id, unit_id, person_id, item_kind, item_ordinal, item_id
    );

-- ---------------------------------------------------------------------------
-- person_state_item_evidence: bounded evidence descriptors for one compiled
-- item. Each descriptor keeps its own source publication / anchor / quote, so
-- a disagreement's other side can point at a different chapter publication.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chronicle.person_state_item_evidence (
    manifest_sha text NOT NULL,
    stream_id uuid NOT NULL,
    unit_id text NOT NULL,
    item_id text NOT NULL,
    descriptor_ordinal integer NOT NULL CHECK (descriptor_ordinal >= 0),
    descriptor_id text NOT NULL CHECK (descriptor_id <> ''),
    source_publication_id uuid NOT NULL
        REFERENCES chronicle.chapter_publications(publication_id) ON DELETE RESTRICT,
    anchor_id text NOT NULL CHECK (anchor_id ~ '^anc_[0-9a-f]{16}$'),
    quote text NOT NULL CHECK (quote <> ''),
    quote_sha256 text NOT NULL CHECK (quote_sha256 ~ '^[0-9a-f]{64}$'),
    attribution text NOT NULL CHECK (
        attribution IN ('narrator', 'quotation', 'annotation', 'hearsay')
    ),
    source_title text NOT NULL CHECK (source_title <> ''),
    phase_id text NOT NULL CHECK (phase_id ~ '^ph_[0-9]{3,}$'),
    relation text NOT NULL CHECK (
        relation IN ('support', 'supplement', 'contradict', 'background')
    ),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (manifest_sha, stream_id, unit_id, item_id, descriptor_ordinal),
    FOREIGN KEY (manifest_sha, stream_id, unit_id, item_id)
        REFERENCES chronicle.person_state_items(
            manifest_sha, stream_id, unit_id, item_id
        ) ON DELETE RESTRICT,
    UNIQUE (manifest_sha, stream_id, unit_id, item_id, descriptor_id)
);

-- ---------------------------------------------------------------------------
-- person_state_disagreements: immutable, catalog-scoped cross-source
-- disagreement index. `source_keys` is the flattened `{chapter_id}:{fact_ref}`
-- membership used to overlay this catalog's recorded explanations onto a
-- published unit without re-running any reasoning. It can only add recorded
-- reasons and uncertainty; it never promotes an uncertain claim to clear.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chronicle.person_state_disagreements (
    disagreement_id text NOT NULL CHECK (disagreement_id ~ '^psd_[0-9a-f]{24}$'),
    catalog_sha text NOT NULL
        REFERENCES chronicle.canonical_catalogs(artifact_sha256) ON DELETE RESTRICT,
    compiler_version text NOT NULL CHECK (compiler_version <> ''),
    topic text NOT NULL CHECK (topic <> ''),
    fact_refs text[] NOT NULL CHECK (cardinality(fact_refs) >= 2),
    phase_ids text[] NOT NULL,
    reason_codes text[] NOT NULL,
    source_keys text[] NOT NULL,
    sources jsonb NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (catalog_sha, disagreement_id)
);

CREATE INDEX IF NOT EXISTS person_state_disagreements_keys_idx
    ON chronicle.person_state_disagreements USING gin (source_keys);

-- ---------------------------------------------------------------------------
-- Immutability: every person-state row is append-only audit history.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION chronicle.forbid_person_state_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Chronicle person-state rows are append-only; publish a new revision instead';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS forbid_person_state_assessment_mutation
    ON chronicle.person_state_assessments;
CREATE TRIGGER forbid_person_state_assessment_mutation
    BEFORE UPDATE OR DELETE ON chronicle.person_state_assessments
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_person_state_mutation();

DROP TRIGGER IF EXISTS forbid_person_state_manifest_mutation
    ON chronicle.person_state_manifests;
CREATE TRIGGER forbid_person_state_manifest_mutation
    BEFORE UPDATE OR DELETE ON chronicle.person_state_manifests
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_person_state_mutation();

DROP TRIGGER IF EXISTS forbid_person_state_unit_people_mutation
    ON chronicle.person_state_unit_people;
CREATE TRIGGER forbid_person_state_unit_people_mutation
    BEFORE UPDATE OR DELETE ON chronicle.person_state_unit_people
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_person_state_mutation();

DROP TRIGGER IF EXISTS forbid_person_state_item_mutation
    ON chronicle.person_state_items;
CREATE TRIGGER forbid_person_state_item_mutation
    BEFORE UPDATE OR DELETE ON chronicle.person_state_items
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_person_state_mutation();

DROP TRIGGER IF EXISTS forbid_person_state_item_evidence_mutation
    ON chronicle.person_state_item_evidence;
CREATE TRIGGER forbid_person_state_item_evidence_mutation
    BEFORE UPDATE OR DELETE ON chronicle.person_state_item_evidence
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_person_state_mutation();

DROP TRIGGER IF EXISTS forbid_person_state_disagreement_mutation
    ON chronicle.person_state_disagreements;
CREATE TRIGGER forbid_person_state_disagreement_mutation
    BEFORE UPDATE OR DELETE ON chronicle.person_state_disagreements
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_person_state_mutation();

-- ---------------------------------------------------------------------------
-- Manifest binding backstop: the stream's own revision/catalog must match the
-- manifest, every cited assessment must exist, and every chapter publication
-- must belong to the stream's snapshot. The store checks this first; this is
-- the database's second fence.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION chronicle.enforce_person_state_manifest_binding()
RETURNS trigger AS $$
DECLARE
    stream_revision uuid;
    stream_catalog text;
    missing_assessments integer;
    publication uuid;
BEGIN
    SELECT revision_id, origin_catalog_sha
      INTO stream_revision, stream_catalog
      FROM chronicle.reading_streams WHERE stream_id = NEW.stream_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'chronicle.person_state_manifests stream % does not exist', NEW.stream_id;
    END IF;
    IF stream_revision IS DISTINCT FROM NEW.revision_id THEN
        RAISE EXCEPTION 'chronicle.person_state_manifests revision % does not match stream %', NEW.revision_id, NEW.stream_id;
    END IF;
    IF stream_catalog IS DISTINCT FROM NEW.origin_catalog_sha THEN
        RAISE EXCEPTION 'chronicle.person_state_manifests catalog % does not match stream % origin catalog', NEW.origin_catalog_sha, NEW.stream_id;
    END IF;

    SELECT count(*) INTO missing_assessments
      FROM unnest(NEW.assessment_hashes) AS a
     WHERE NOT EXISTS (
         SELECT 1 FROM chronicle.person_state_assessments WHERE assessment_sha = a
     );
    IF missing_assessments <> 0 THEN
        RAISE EXCEPTION 'chronicle.person_state_manifests cites % unpersisted assessment(s)', missing_assessments;
    END IF;

    FOREACH publication IN ARRAY NEW.chapter_publication_ids LOOP
        IF NOT EXISTS (
            SELECT 1 FROM chronicle.reading_streams
             WHERE stream_id = NEW.stream_id
               AND publication = ANY (chapter_publication_ids)
        ) THEN
            RAISE EXCEPTION 'chronicle.person_state_manifests publication % is not part of stream %', publication, NEW.stream_id;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_person_state_manifest_binding
    ON chronicle.person_state_manifests;
CREATE TRIGGER enforce_person_state_manifest_binding
    BEFORE INSERT ON chronicle.person_state_manifests
    FOR EACH ROW EXECUTE FUNCTION chronicle.enforce_person_state_manifest_binding();
