-- Chronicle C2-R2-T05 continuous-reading stream index (application-owned).
--
-- Strictly additive over 0006_chronicle_chapters.sql: it creates the four
-- immutable reading tables fixed by continuous-reading.md section 4 and adds
-- no column, constraint or trigger to any first-round table. It never copies
-- translation text, source anchors, entity tables or model runs; a reading
-- unit points at the existing chapter publication that already owns the body
-- text. It never touches Loom Runtime/World/Timeline/Work/Binding authority
-- (Architecture Amendment 0006, CHRONICLE_DATABASE_URL only). It never
-- weakens the 0005 Reader Presentation Claim-only support constraint or the
-- 0006 chapter binding guards.
--
-- Authority: continuous-reading.md sections 4-5. reading_store.py holds the
-- new tables. The atomic publish transaction, worker wiring and completeness
-- gate belong to T06; T07/T08 read through the SELECT-only helpers here and
-- must not build a second read path. Catalog membership is decided only by
-- the immutable catalog payload (never by the global representation tables or
-- by a time ceiling); the catalog publication_sequence is only a range bound.
--
-- Conventions: UUIDv7 stream/publication identity, immutable JSONB payloads,
-- append-only rows. Foreign keys and unique constraints stop cross-stream and
-- duplicate indexes; binding triggers close the gaps that array columns and
-- composite parent links cannot express (nonexistent publication, mismatched
-- revision, snapshot-external event representation).

-- ---------------------------------------------------------------------------
-- reading_streams: one immutable reading version per document revision.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chronicle.reading_streams (
    stream_id uuid PRIMARY KEY CHECK (uuid_extract_version(stream_id) = 7),
    revision_id uuid NOT NULL UNIQUE
        REFERENCES chronicle.document_revisions(revision_id) ON DELETE RESTRICT,
    document_id uuid NOT NULL
        REFERENCES chronicle.documents(document_id) ON DELETE RESTRICT,
    origin_catalog_sha text NOT NULL CHECK (origin_catalog_sha ~ '^[0-9a-f]{64}$')
        REFERENCES chronicle.canonical_catalogs(artifact_sha256) ON DELETE RESTRICT,
    manifest_sha text NOT NULL CHECK (manifest_sha ~ '^[0-9a-f]{64}$'),
    chapter_publication_ids uuid[] NOT NULL
        CHECK (cardinality(chapter_publication_ids) > 0),
    unit_count integer NOT NULL CHECK (unit_count >= 0),
    group_count integer NOT NULL CHECK (group_count >= 0),
    manifest jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS reading_streams_document_idx
    ON chronicle.reading_streams(document_id);
CREATE INDEX IF NOT EXISTS reading_streams_catalog_idx
    ON chronicle.reading_streams(origin_catalog_sha);

-- ---------------------------------------------------------------------------
-- reading_units: one row per complete translation block, in stream order.
-- The body text is never duplicated here: it is read from chapter_publications
-- through publication_id + block_id.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chronicle.reading_units (
    stream_id uuid NOT NULL
        REFERENCES chronicle.reading_streams(stream_id) ON DELETE RESTRICT,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    unit_id text NOT NULL UNIQUE CHECK (unit_id <> ''),
    publication_id uuid NOT NULL
        REFERENCES chronicle.chapter_publications(publication_id) ON DELETE RESTRICT,
    artifact_sha256 text NOT NULL CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$')
        REFERENCES chronicle.chapter_artifacts(artifact_sha256) ON DELETE RESTRICT,
    chapter_id text NOT NULL CHECK (chapter_id <> ''),
    block_id text NOT NULL CHECK (block_id <> ''),
    text_hash text NOT NULL CHECK (text_hash ~ '^[0-9a-f]{64}$'),
    group_id text NOT NULL CHECK (group_id <> ''),
    narrative_time jsonb NOT NULL,
    segments jsonb NOT NULL,
    context_entities jsonb NOT NULL,
    source_anchor_ids jsonb NOT NULL,
    continues_previous boolean NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (stream_id, ordinal),
    UNIQUE (stream_id, unit_id)
);

CREATE INDEX IF NOT EXISTS reading_units_publication_idx
    ON chronicle.reading_units(publication_id);
CREATE INDEX IF NOT EXISTS reading_units_group_idx
    ON chronicle.reading_units(stream_id, group_id);

-- ---------------------------------------------------------------------------
-- reading_time_groups: precompiled narrative-time axis segments in order.
-- Group identity is fixed at publish time; pagination never re-creates it.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chronicle.reading_time_groups (
    stream_id uuid NOT NULL
        REFERENCES chronicle.reading_streams(stream_id) ON DELETE RESTRICT,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    group_id text NOT NULL CHECK (group_id <> ''),
    first_unit_ordinal integer NOT NULL CHECK (first_unit_ordinal >= 0),
    last_unit_ordinal integer NOT NULL CHECK (last_unit_ordinal >= first_unit_ordinal),
    first_unit_id text NOT NULL CHECK (first_unit_id <> ''),
    last_unit_id text NOT NULL CHECK (last_unit_id <> ''),
    unit_count integer NOT NULL CHECK (unit_count > 0),
    year_key text NOT NULL CHECK (year_key <> ''),
    period_key text NOT NULL CHECK (period_key <> ''),
    year_label text,
    period_label text NOT NULL CHECK (period_label <> ''),
    precision text NOT NULL CHECK (
        precision IN ('day', 'month', 'year', 'range', 'mixed', 'unknown', 'approximate')
    ),
    observations jsonb NOT NULL,
    continues_previous boolean NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (stream_id, ordinal),
    UNIQUE (stream_id, group_id)
);

-- ---------------------------------------------------------------------------
-- reading_event_occurrences: exact reverse lookup from a canonical event (or
-- one of its source representations) back to a reading unit / span. A "current"
-- row marks the unit's current-event list; a "span" row marks one resolved
-- translation span. Ambiguous/unresolved spans have no canonical target and are
-- therefore never indexed here.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chronicle.reading_event_occurrences (
    occurrence_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stream_id uuid NOT NULL,
    unit_ordinal integer NOT NULL,
    event_kind text NOT NULL CHECK (event_kind IN ('span', 'current')),
    span_id text,
    canonical_event_id uuid NOT NULL
        REFERENCES chronicle.canonical_events(canonical_id) ON DELETE RESTRICT,
    relation text NOT NULL CHECK (
        relation IN ('current', 'retrospective', 'foreshadow', 'background', 'uncertain')
    ),
    bundle_label text NOT NULL CHECK (bundle_label <> ''),
    record_ref text NOT NULL CHECK (record_ref <> ''),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (stream_id, unit_ordinal)
        REFERENCES chronicle.reading_units(stream_id, ordinal) ON DELETE RESTRICT,
    FOREIGN KEY (bundle_label, record_ref)
        REFERENCES chronicle.staged_events(bundle_label, record_ref) ON DELETE RESTRICT,
    CHECK (
        (event_kind = 'span' AND span_id IS NOT NULL)
        OR (event_kind = 'current' AND span_id IS NULL)
    )
);

-- Reverse lookup by event, bounded by stream/unit: the index supports
-- "which published positions talk about this event" without scanning the
-- whole body corpus. The stream/ordinal direction is already the reading_units
-- primary key.
CREATE INDEX IF NOT EXISTS reading_event_occurrences_event_idx
    ON chronicle.reading_event_occurrences(canonical_event_id, relation, stream_id, unit_ordinal);
CREATE INDEX IF NOT EXISTS reading_event_occurrences_ref_idx
    ON chronicle.reading_event_occurrences(bundle_label, record_ref);

-- ---------------------------------------------------------------------------
-- Immutability: reading indexes are append-only audit history. A corrected
-- stream is a new revision, never an in-place edit.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION chronicle.forbid_reading_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Chronicle reading rows are append-only; publish a new revision instead';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS forbid_reading_stream_mutation ON chronicle.reading_streams;
CREATE TRIGGER forbid_reading_stream_mutation
    BEFORE UPDATE OR DELETE ON chronicle.reading_streams
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_reading_mutation();

DROP TRIGGER IF EXISTS forbid_reading_unit_mutation ON chronicle.reading_units;
CREATE TRIGGER forbid_reading_unit_mutation
    BEFORE UPDATE OR DELETE ON chronicle.reading_units
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_reading_mutation();

DROP TRIGGER IF EXISTS forbid_reading_group_mutation ON chronicle.reading_time_groups;
CREATE TRIGGER forbid_reading_group_mutation
    BEFORE UPDATE OR DELETE ON chronicle.reading_time_groups
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_reading_mutation();

DROP TRIGGER IF EXISTS forbid_reading_occurrence_mutation ON chronicle.reading_event_occurrences;
CREATE TRIGGER forbid_reading_occurrence_mutation
    BEFORE UPDATE OR DELETE ON chronicle.reading_event_occurrences
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_reading_mutation();

-- ---------------------------------------------------------------------------
-- Binding backstops: an array column cannot carry a foreign key, so the stream
-- trigger proves every chapter publication exists, is unique and belongs to
-- the stream's own revision/document. This is the second fence behind the
-- store's fail-closed pre-checks.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION chronicle.enforce_reading_stream_binding()
RETURNS trigger AS $$
DECLARE
    revision_document uuid;
    publication uuid;
    pub_revision uuid;
    pub_document uuid;
    distinct_publications integer;
BEGIN
    SELECT document_id INTO revision_document
      FROM chronicle.document_revisions WHERE revision_id = NEW.revision_id;
    IF revision_document IS DISTINCT FROM NEW.document_id THEN
        RAISE EXCEPTION 'chronicle.reading_streams document % does not match revision % of stream', NEW.document_id, NEW.revision_id;
    END IF;

    SELECT count(DISTINCT value) INTO distinct_publications
      FROM unnest(NEW.chapter_publication_ids) AS value;
    IF distinct_publications IS DISTINCT FROM cardinality(NEW.chapter_publication_ids) THEN
        RAISE EXCEPTION 'chronicle.reading_streams repeats a chapter publication id';
    END IF;

    FOREACH publication IN ARRAY NEW.chapter_publication_ids LOOP
        SELECT revision_id, document_id INTO pub_revision, pub_document
          FROM chronicle.chapter_publications WHERE publication_id = publication;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'chronicle.reading_streams chapter publication % does not exist', publication;
        END IF;
        IF pub_revision IS DISTINCT FROM NEW.revision_id
           OR pub_document IS DISTINCT FROM NEW.document_id THEN
            RAISE EXCEPTION 'chronicle.reading_streams chapter publication % belongs to another revision/document', publication;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_reading_stream_binding ON chronicle.reading_streams;
CREATE TRIGGER enforce_reading_stream_binding
    BEFORE INSERT ON chronicle.reading_streams
    FOR EACH ROW EXECUTE FUNCTION chronicle.enforce_reading_stream_binding();

-- A reading unit may only cite a chapter publication the stream already lists,
-- and its artifact/chapter must match that publication. This rejects both
-- cross-stream citations and bodies swapped under the same revision.
CREATE OR REPLACE FUNCTION chronicle.enforce_reading_unit_binding()
RETURNS trigger AS $$
DECLARE
    stream_revision uuid;
    pub_revision uuid;
    pub_document uuid;
    pub_artifact text;
    pub_chapter text;
BEGIN
    SELECT revision_id INTO stream_revision
      FROM chronicle.reading_streams WHERE stream_id = NEW.stream_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'chronicle.reading_units stream % does not exist', NEW.stream_id;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM chronicle.reading_streams
         WHERE stream_id = NEW.stream_id
           AND NEW.publication_id = ANY (chapter_publication_ids)
    ) THEN
        RAISE EXCEPTION 'chronicle.reading_units publication % is not part of stream %', NEW.publication_id, NEW.stream_id;
    END IF;

    SELECT revision_id, document_id, artifact_sha256, chapter_id
      INTO pub_revision, pub_document, pub_artifact, pub_chapter
      FROM chronicle.chapter_publications WHERE publication_id = NEW.publication_id;
    IF pub_revision IS DISTINCT FROM stream_revision THEN
        RAISE EXCEPTION 'chronicle.reading_units publication % does not belong to the stream revision', NEW.publication_id;
    END IF;
    IF pub_artifact IS DISTINCT FROM NEW.artifact_sha256 THEN
        RAISE EXCEPTION 'chronicle.reading_units artifact % does not match publication artifact %', NEW.artifact_sha256, pub_artifact;
    END IF;
    IF pub_chapter IS DISTINCT FROM NEW.chapter_id THEN
        RAISE EXCEPTION 'chronicle.reading_units chapter % does not match publication chapter %', NEW.chapter_id, pub_chapter;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_reading_unit_binding ON chronicle.reading_units;
CREATE TRIGGER enforce_reading_unit_binding
    BEFORE INSERT ON chronicle.reading_units
    FOR EACH ROW EXECUTE FUNCTION chronicle.enforce_reading_unit_binding();

-- A time group must cover an existing, contiguous run of its own units.
CREATE OR REPLACE FUNCTION chronicle.enforce_reading_group_binding()
RETURNS trigger AS $$
DECLARE
    first_id text;
    last_id text;
    covered integer;
    mismatched integer;
BEGIN
    SELECT unit_id INTO first_id
      FROM chronicle.reading_units
     WHERE stream_id = NEW.stream_id AND ordinal = NEW.first_unit_ordinal;
    IF NOT FOUND OR first_id IS DISTINCT FROM NEW.first_unit_id THEN
        RAISE EXCEPTION 'chronicle.reading_time_groups first unit % does not match stream % ordinal %', NEW.first_unit_id, NEW.stream_id, NEW.first_unit_ordinal;
    END IF;
    SELECT unit_id INTO last_id
      FROM chronicle.reading_units
     WHERE stream_id = NEW.stream_id AND ordinal = NEW.last_unit_ordinal;
    IF NOT FOUND OR last_id IS DISTINCT FROM NEW.last_unit_id THEN
        RAISE EXCEPTION 'chronicle.reading_time_groups last unit % does not match stream % ordinal %', NEW.last_unit_id, NEW.stream_id, NEW.last_unit_ordinal;
    END IF;

    SELECT count(*), count(*) FILTER (WHERE group_id IS DISTINCT FROM NEW.group_id)
      INTO covered, mismatched
      FROM chronicle.reading_units
     WHERE stream_id = NEW.stream_id
       AND ordinal BETWEEN NEW.first_unit_ordinal AND NEW.last_unit_ordinal;
    IF covered IS DISTINCT FROM NEW.unit_count THEN
        RAISE EXCEPTION 'chronicle.reading_time_groups unit_count % does not match covered units %', NEW.unit_count, covered;
    END IF;
    IF mismatched <> 0 THEN
        RAISE EXCEPTION 'chronicle.reading_time_groups covers units with a different group_id';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_reading_group_binding ON chronicle.reading_time_groups;
CREATE TRIGGER enforce_reading_group_binding
    BEFORE INSERT ON chronicle.reading_time_groups
    FOR EACH ROW EXECUTE FUNCTION chronicle.enforce_reading_group_binding();

-- Snapshot membership backstop: an occurrence may only cite a canonical event
-- through a source representation that the stream's origin catalog payload
-- actually lists. The immutable catalog payload is the member authority; the
-- global representation tables are never consulted here.
CREATE OR REPLACE FUNCTION chronicle.enforce_reading_occurrence_membership()
RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM chronicle.reading_streams s
          JOIN chronicle.canonical_catalogs c
            ON c.artifact_sha256 = s.origin_catalog_sha
          CROSS JOIN LATERAL jsonb_array_elements(c.payload -> 'canonical_events') AS ev
          CROSS JOIN LATERAL jsonb_array_elements(ev -> 'representations') AS rep
         WHERE s.stream_id = NEW.stream_id
           AND ev ->> 'canonical_id' = NEW.canonical_event_id::text
           AND rep ->> 'bundle' = NEW.bundle_label
           AND rep ->> 'ref' = NEW.record_ref
    ) THEN
        RAISE EXCEPTION 'chronicle.reading_event_occurrences %:% is not a member of the stream snapshot catalog', NEW.bundle_label, NEW.record_ref;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_reading_occurrence_membership ON chronicle.reading_event_occurrences;
CREATE TRIGGER enforce_reading_occurrence_membership
    BEFORE INSERT ON chronicle.reading_event_occurrences
    FOR EACH ROW EXECUTE FUNCTION chronicle.enforce_reading_occurrence_membership();
