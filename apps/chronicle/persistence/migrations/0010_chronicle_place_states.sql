-- Chronicle C2-R3-T05 place-state persistence (application-owned).
--
-- This migration is additive over 0009_chronicle_person_states.sql.  The
-- people tables retain their deliberately narrow office/title/affiliation
-- dimension check; administration/control state has a separate immutable
-- index so place reading can ship without widening an already-published
-- schema.  The publication transaction writes these rows beside the people
-- rows and the read API only exposes snapshot-bound SELECTs.
--
-- Authority: person-state-reading.md sections 6-7 and third-round T05/T08/T09.
-- Place state is an administration/control assertion.  Visits, participation
-- and other event occurrences are not silently promoted into place control.

-- ---------------------------------------------------------------------------
-- person_state_unit_places: one summary anchor for each place represented in a
-- published reading unit.  The full flat place items below are the public page
-- rows; this table supplies existence and composite-FK membership fencing.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chronicle.person_state_unit_places (
    manifest_sha text NOT NULL,
    stream_id uuid NOT NULL,
    unit_id text NOT NULL CHECK (unit_id <> ''),
    place_id text NOT NULL CHECK (place_id <> ''),
    place_ordinal integer NOT NULL CHECK (place_ordinal >= 0),
    name text NOT NULL CHECK (name <> ''),
    item_count integer NOT NULL CHECK (item_count >= 0),
    administration_count integer NOT NULL CHECK (administration_count >= 0),
    control_count integer NOT NULL CHECK (control_count >= 0),
    certainty text NOT NULL CHECK (certainty IN ('clear', 'uncertain')),
    reason_codes text[] NOT NULL,
    phases jsonb NOT NULL,
    preview_places jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (manifest_sha, stream_id, unit_id, place_id),
    FOREIGN KEY (manifest_sha, stream_id)
        REFERENCES chronicle.person_state_manifests(manifest_sha, stream_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (stream_id, unit_id)
        REFERENCES chronicle.reading_units(stream_id, unit_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS person_state_unit_places_page_idx
    ON chronicle.person_state_unit_places(stream_id, unit_id, place_ordinal, place_id);

-- ---------------------------------------------------------------------------
-- person_state_place_items: immutable administration/control assertions.  The
-- payload is retained as the exact T01 place_state_item DTO so reads do not
-- reconstruct or reinterpret compiler output.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chronicle.person_state_place_items (
    manifest_sha text NOT NULL,
    stream_id uuid NOT NULL,
    unit_id text NOT NULL,
    place_id text NOT NULL,
    item_id text NOT NULL CHECK (item_id ~ '^psi_[0-9a-f]{24}$'),
    dimension text NOT NULL CHECK (dimension IN ('administration', 'control')),
    value text,
    controller text,
    certainty text NOT NULL CHECK (certainty IN ('clear', 'uncertain')),
    reason_codes text[] NOT NULL,
    reason_text text NOT NULL,
    phase_ids text[] NOT NULL,
    current boolean NOT NULL,
    source_facts jsonb NOT NULL,
    evidence_count integer NOT NULL CHECK (evidence_count >= 0),
    item_ordinal integer NOT NULL CHECK (item_ordinal >= 0),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (manifest_sha, stream_id, unit_id, item_id),
    UNIQUE (manifest_sha, stream_id, unit_id, place_id, item_id),
    FOREIGN KEY (manifest_sha, stream_id, unit_id, place_id)
        REFERENCES chronicle.person_state_unit_places(
            manifest_sha, stream_id, unit_id, place_id
        ) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS person_state_place_items_page_idx
    ON chronicle.person_state_place_items(
        stream_id, unit_id, place_id, item_ordinal, item_id
    );

-- ---------------------------------------------------------------------------
-- person_state_place_item_evidence: source-anchored descriptors for one place
-- assertion.  Publication membership is checked by the store before the
-- insert and by the stream/manifest binding already established in 0009.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chronicle.person_state_place_item_evidence (
    manifest_sha text NOT NULL,
    stream_id uuid NOT NULL,
    unit_id text NOT NULL,
    place_id text NOT NULL,
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
    PRIMARY KEY (
        manifest_sha, stream_id, unit_id, place_id, item_id, descriptor_ordinal
    ),
    FOREIGN KEY (manifest_sha, stream_id, unit_id, place_id, item_id)
        REFERENCES chronicle.person_state_place_items(
            manifest_sha, stream_id, unit_id, place_id, item_id
        ) ON DELETE RESTRICT,
    UNIQUE (
        manifest_sha, stream_id, unit_id, place_id, item_id, descriptor_id
    )
);

CREATE INDEX IF NOT EXISTS person_state_place_item_evidence_page_idx
    ON chronicle.person_state_place_item_evidence(
        stream_id, unit_id, place_id, item_id, descriptor_ordinal
    );

-- Place state is append-only just like the people state published by 0009.
DROP TRIGGER IF EXISTS forbid_person_state_unit_places_mutation
    ON chronicle.person_state_unit_places;
CREATE TRIGGER forbid_person_state_unit_places_mutation
    BEFORE UPDATE OR DELETE ON chronicle.person_state_unit_places
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_person_state_mutation();

DROP TRIGGER IF EXISTS forbid_person_state_place_item_mutation
    ON chronicle.person_state_place_items;
CREATE TRIGGER forbid_person_state_place_item_mutation
    BEFORE UPDATE OR DELETE ON chronicle.person_state_place_items
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_person_state_mutation();

DROP TRIGGER IF EXISTS forbid_person_state_place_item_evidence_mutation
    ON chronicle.person_state_place_item_evidence;
CREATE TRIGGER forbid_person_state_place_item_evidence_mutation
    BEFORE UPDATE OR DELETE ON chronicle.person_state_place_item_evidence
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_person_state_mutation();
