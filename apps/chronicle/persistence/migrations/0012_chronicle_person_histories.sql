-- C3-T12: independent, source-grounded person-history production.
--
-- This is additive over the generic historical-narrative product.  Person
-- histories have their own candidate/acceptance/publication frontier so a
-- person summary or biography can never be published by widening a main
-- history row.  The existing ingestion job, ReviewItem, output and lease
-- authorities remain the durable execution boundary.

CREATE TABLE IF NOT EXISTS chronicle.person_history_candidates (
    candidate_sha text PRIMARY KEY CHECK (candidate_sha ~ '^[0-9a-f]{64}$'),
    job_id uuid NOT NULL REFERENCES chronicle.ingestion_jobs(job_id) ON DELETE RESTRICT,
    kind text NOT NULL CHECK (kind IN ('summary', 'prose')),
    review_id uuid UNIQUE REFERENCES chronicle.review_items(review_id) ON DELETE RESTRICT,
    parent_candidate_sha text
        CHECK (parent_candidate_sha IS NULL OR parent_candidate_sha ~ '^[0-9a-f]{64}$'),
    revision_no integer NOT NULL CHECK (revision_no >= 0),
    upstream_candidate_sha text
        CHECK (upstream_candidate_sha IS NULL OR upstream_candidate_sha ~ '^[0-9a-f]{64}$'),
    context_sha text NOT NULL CHECK (context_sha ~ '^[0-9a-f]{64}$'),
    context_payload jsonb NOT NULL,
    candidate_payload jsonb NOT NULL,
    model_version text NOT NULL CHECK (model_version <> ''),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, kind, revision_no)
);

CREATE INDEX IF NOT EXISTS person_history_candidates_frontier_idx
    ON chronicle.person_history_candidates(job_id, kind, revision_no DESC, candidate_sha DESC);

CREATE TABLE IF NOT EXISTS chronicle.person_history_acceptances (
    acceptance_id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES chronicle.ingestion_jobs(job_id) ON DELETE RESTRICT,
    kind text NOT NULL CHECK (kind IN ('summary', 'prose')),
    acceptance_type text NOT NULL CHECK (acceptance_type IN ('human', 'policy_model_review')),
    policy_version text NOT NULL CHECK (policy_version <> ''),
    input_sha256 text NOT NULL CHECK (input_sha256 ~ '^[0-9a-f]{64}$'),
    candidate_sha256 text NOT NULL CHECK (candidate_sha256 ~ '^[0-9a-f]{64}$'),
    draft_sha256 text NOT NULL CHECK (draft_sha256 ~ '^[0-9a-f]{64}$'),
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    pipeline_fingerprint text,
    model_output_sha256s text[] NOT NULL DEFAULT '{}'::text[],
    model_opinion_sha256s text[] NOT NULL DEFAULT '{}'::text[],
    decision text NOT NULL CHECK (decision = 'accept'),
    decision_reason text NOT NULL CHECK (decision_reason <> ''),
    review_id uuid UNIQUE REFERENCES chronicle.review_items(review_id) ON DELETE RESTRICT,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, kind, candidate_sha256),
    CHECK ((acceptance_type = 'human' AND review_id IS NOT NULL)
        OR (acceptance_type = 'policy_model_review' AND review_id IS NULL)),
    CHECK (draft_sha256 = content_sha256)
);

CREATE INDEX IF NOT EXISTS person_history_acceptances_job_kind_idx
    ON chronicle.person_history_acceptances(job_id, kind, created_at DESC);

CREATE TABLE IF NOT EXISTS chronicle.person_histories (
    version_sha text PRIMARY KEY CHECK (version_sha ~ '^[0-9a-f]{64}$'),
    job_id uuid NOT NULL UNIQUE REFERENCES chronicle.ingestion_jobs(job_id) ON DELETE RESTRICT,
    person_id uuid NOT NULL REFERENCES chronicle.canonical_entities(canonical_id) ON DELETE RESTRICT,
    catalog_sha text NOT NULL REFERENCES chronicle.canonical_catalogs(artifact_sha256) ON DELETE RESTRICT,
    context_sha text NOT NULL CHECK (context_sha ~ '^[0-9a-f]{64}$'),
    source_publication_ids uuid[] NOT NULL CHECK (cardinality(source_publication_ids) > 0),
    summary_candidate_sha text NOT NULL REFERENCES chronicle.person_history_candidates(candidate_sha),
    prose_candidate_sha text NOT NULL REFERENCES chronicle.person_history_candidates(candidate_sha),
    summary_acceptance_id uuid NOT NULL REFERENCES chronicle.person_history_acceptances(acceptance_id),
    prose_acceptance_id uuid NOT NULL REFERENCES chronicle.person_history_acceptances(acceptance_id),
    summary_sha text NOT NULL CHECK (summary_sha ~ '^[0-9a-f]{64}$'),
    prose_sha text NOT NULL CHECK (prose_sha ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL,
    publication_sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    published_at timestamptz NOT NULL DEFAULT now(),
    CHECK (summary_candidate_sha <> prose_candidate_sha),
    CHECK (summary_acceptance_id <> prose_acceptance_id),
    CHECK (summary_sha <> prose_sha)
);

CREATE INDEX IF NOT EXISTS person_histories_person_idx
    ON chronicle.person_histories(person_id, publication_sequence DESC);
CREATE INDEX IF NOT EXISTS person_histories_catalog_idx
    ON chronicle.person_histories(catalog_sha, publication_sequence DESC);

CREATE TABLE IF NOT EXISTS chronicle.person_history_mappings (
    person_history_version_sha text NOT NULL
        REFERENCES chronicle.person_histories(version_sha) ON DELETE RESTRICT,
    person_phase_id text NOT NULL CHECK (person_phase_id ~ '^[a-z][a-zA-Z0-9_-]{0,63}$'),
    mapping_no integer NOT NULL CHECK (mapping_no >= 0),
    mapping_status text NOT NULL CHECK (mapping_status IN ('mapped', 'ambiguous', 'unmapped')),
    main_history_version_sha text
        REFERENCES chronicle.historical_narratives(version_sha) ON DELETE RESTRICT,
    main_history_paragraph_id text,
    main_history_phase_id text,
    reason text NOT NULL CHECK (reason <> ''),
    evidence_conclusion_ids text[] NOT NULL DEFAULT '{}'::text[],
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (person_history_version_sha, person_phase_id, mapping_no),
    CHECK (
        (mapping_status = 'unmapped'
         AND main_history_version_sha IS NULL
         AND main_history_paragraph_id IS NULL)
        OR
        (mapping_status IN ('mapped', 'ambiguous')
         AND main_history_version_sha IS NOT NULL
         AND main_history_paragraph_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS person_history_mappings_main_idx
    ON chronicle.person_history_mappings(main_history_version_sha, main_history_paragraph_id);

CREATE OR REPLACE FUNCTION chronicle.forbid_person_history_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Chronicle person-history rows are append-only; publish a new revision instead';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER person_history_candidates_immutable
    BEFORE UPDATE OR DELETE ON chronicle.person_history_candidates
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_person_history_mutation();
CREATE TRIGGER person_history_acceptances_immutable
    BEFORE UPDATE OR DELETE ON chronicle.person_history_acceptances
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_person_history_mutation();
CREATE TRIGGER person_histories_immutable
    BEFORE UPDATE OR DELETE ON chronicle.person_histories
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_person_history_mutation();
CREATE TRIGGER person_history_mappings_immutable
    BEFORE UPDATE OR DELETE ON chronicle.person_history_mappings
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_person_history_mutation();

CREATE OR REPLACE FUNCTION chronicle.person_history_candidate_is_current(
    p_job_id uuid, p_kind text, p_candidate_sha text
) RETURNS boolean AS $$
DECLARE current_sha text;
BEGIN
    SELECT candidate_sha INTO current_sha
    FROM chronicle.person_history_candidates
    WHERE job_id = p_job_id AND kind = p_kind
    ORDER BY revision_no DESC, candidate_sha DESC
    LIMIT 1;
    RETURN current_sha IS NOT NULL AND current_sha = p_candidate_sha;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION chronicle.check_person_history_candidate()
RETURNS trigger AS $$
DECLARE expected_revision integer;
DECLARE parent_context_sha text;
DECLARE expected_digest text;
BEGIN
    IF NEW.revision_no = 0 THEN
        IF NEW.parent_candidate_sha IS NOT NULL THEN
            RAISE EXCEPTION 'person-history initial candidate cannot have a parent';
        END IF;
        IF EXISTS (
            SELECT 1 FROM chronicle.person_history_candidates
            WHERE job_id = NEW.job_id AND kind = NEW.kind
        ) THEN
            RAISE EXCEPTION 'person-history initial candidate already exists';
        END IF;
    ELSE
        IF NEW.parent_candidate_sha IS NULL OR NOT chronicle.person_history_candidate_is_current(
            NEW.job_id, NEW.kind, NEW.parent_candidate_sha
        ) THEN
            RAISE EXCEPTION 'person-history revision parent is not the current candidate frontier';
        END IF;
        SELECT coalesce(max(revision_no), -1) + 1 INTO expected_revision
        FROM chronicle.person_history_candidates
        WHERE job_id = NEW.job_id AND kind = NEW.kind;
        IF NEW.revision_no <> expected_revision THEN
            RAISE EXCEPTION 'person-history revision is not the next append-only version';
        END IF;
        SELECT context_sha INTO parent_context_sha
        FROM chronicle.person_history_candidates
        WHERE candidate_sha = NEW.parent_candidate_sha;
        IF parent_context_sha IS DISTINCT FROM NEW.context_sha THEN
            RAISE EXCEPTION 'person-history revision changed its frozen context';
        END IF;
    END IF;

    IF jsonb_typeof(NEW.context_payload) IS DISTINCT FROM 'object'
       OR jsonb_typeof(NEW.candidate_payload) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'person-history candidate payloads must be JSON objects';
    END IF;
    IF chronicle.jsonb_sha256(NEW.context_payload) IS DISTINCT FROM NEW.context_sha THEN
        RAISE EXCEPTION 'person-history candidate context hash does not match its payload';
    END IF;
    IF NEW.revision_no = 0 THEN
        expected_digest := chronicle.jsonb_sha256(jsonb_build_object(
            'job_id', NEW.job_id::text,
            'kind', NEW.kind,
            'context', NEW.context_payload,
            'candidate', NEW.candidate_payload,
            'upstream_candidate_sha', NEW.upstream_candidate_sha
        ));
    ELSE
        expected_digest := chronicle.jsonb_sha256(jsonb_build_object(
            'job_id', NEW.job_id::text,
            'kind', NEW.kind,
            'context', NEW.context_payload,
            'candidate', NEW.candidate_payload,
            'parent_candidate_sha', NEW.parent_candidate_sha,
            'revision_no', NEW.revision_no,
            'upstream_candidate_sha', NEW.upstream_candidate_sha
        ));
    END IF;
    IF expected_digest IS DISTINCT FROM NEW.candidate_sha THEN
        RAISE EXCEPTION 'person-history candidate digest does not match its revision payload';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER person_history_candidate_guard
    BEFORE INSERT ON chronicle.person_history_candidates
    FOR EACH ROW EXECUTE FUNCTION chronicle.check_person_history_candidate();

CREATE OR REPLACE FUNCTION chronicle.check_person_history_acceptance()
RETURNS trigger AS $$
DECLARE candidate_context_sha text;
DECLARE candidate_job_id uuid;
DECLARE candidate_kind text;
DECLARE candidate_payload jsonb;
BEGIN
    SELECT c.context_sha, c.job_id, c.kind, c.candidate_payload
      INTO candidate_context_sha, candidate_job_id, candidate_kind, candidate_payload
    FROM chronicle.person_history_candidates c
    WHERE c.candidate_sha = NEW.candidate_sha256;
    IF candidate_job_id IS NULL
       OR candidate_job_id <> NEW.job_id
       OR candidate_kind <> NEW.kind
       OR candidate_context_sha <> NEW.input_sha256 THEN
        RAISE EXCEPTION 'person-history acceptance is not bound to its candidate and context';
    END IF;
    IF NOT chronicle.person_history_candidate_is_current(
        NEW.job_id, NEW.kind, NEW.candidate_sha256
    ) THEN
        RAISE EXCEPTION 'person-history acceptance requires the current candidate frontier';
    END IF;
    IF chronicle.jsonb_sha256(candidate_payload) IS DISTINCT FROM NEW.draft_sha256
       OR NEW.content_sha256 IS DISTINCT FROM NEW.draft_sha256 THEN
        RAISE EXCEPTION 'person-history acceptance content hash is not derived from the current candidate';
    END IF;
    IF NEW.payload->>'schema' IS DISTINCT FROM 'chronicle.person-history-acceptance'
       OR NEW.payload->>'version' IS DISTINCT FROM '0.1'
       OR NEW.payload->>'acceptance_type' IS DISTINCT FROM NEW.acceptance_type
       OR NEW.payload->>'job_id' IS DISTINCT FROM NEW.job_id::text
       OR NEW.payload->>'kind' IS DISTINCT FROM NEW.kind
       OR NEW.payload->>'policy_version' IS DISTINCT FROM NEW.policy_version
       OR NEW.payload->>'input_sha256' IS DISTINCT FROM NEW.input_sha256
       OR NEW.payload->>'candidate_sha256' IS DISTINCT FROM NEW.candidate_sha256
       OR NEW.payload->>'draft_sha256' IS DISTINCT FROM NEW.draft_sha256
       OR NEW.payload->>'content_sha256' IS DISTINCT FROM NEW.content_sha256
       OR NEW.payload->>'decision' IS DISTINCT FROM NEW.decision
       OR NEW.payload->>'decision_reason' IS DISTINCT FROM NEW.decision_reason
       OR COALESCE(NEW.payload->'pipeline_fingerprint', 'null'::jsonb)
            IS DISTINCT FROM COALESCE(to_jsonb(NEW.pipeline_fingerprint), 'null'::jsonb)
       OR COALESCE(NEW.payload->'model_output_sha256s', 'null'::jsonb)
            IS DISTINCT FROM to_jsonb(NEW.model_output_sha256s)
       OR COALESCE(NEW.payload->'model_opinion_sha256s', 'null'::jsonb)
            IS DISTINCT FROM to_jsonb(NEW.model_opinion_sha256s)
       OR COALESCE(NEW.payload->'review_id', 'null'::jsonb)
            IS DISTINCT FROM COALESCE(to_jsonb(NEW.review_id), 'null'::jsonb)
       OR NEW.payload->>'receipt_sha256' IS NULL
       OR chronicle.jsonb_sha256(NEW.payload - 'receipt_sha256')
            IS DISTINCT FROM NEW.payload->>'receipt_sha256' THEN
        RAISE EXCEPTION 'person-history acceptance receipt does not match its relational row';
    END IF;
    IF jsonb_typeof(NEW.payload->'reviewed_conclusion_ids') IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'person-history acceptance receipt has no reviewed conclusion list';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(NEW.payload->'reviewed_conclusion_ids') AS ids(value)
        WHERE jsonb_typeof(ids.value) IS DISTINCT FROM 'string'
    ) THEN
        RAISE EXCEPTION 'person-history acceptance reviewed conclusion ids are invalid';
    END IF;
    IF NEW.payload->>'draft_sha256' IS DISTINCT FROM NEW.payload->>'content_sha256' THEN
        RAISE EXCEPTION 'person-history acceptance draft/content hashes differ';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER person_history_acceptance_guard
    BEFORE INSERT ON chronicle.person_history_acceptances
    FOR EACH ROW EXECUTE FUNCTION chronicle.check_person_history_acceptance();

CREATE OR REPLACE FUNCTION chronicle.check_person_history_publication()
RETURNS trigger AS $$
DECLARE summary_kind text;
DECLARE prose_kind text;
DECLARE summary_job uuid;
DECLARE prose_job uuid;
DECLARE summary_context text;
DECLARE prose_context text;
DECLARE summary_accept_job uuid;
DECLARE prose_accept_job uuid;
DECLARE summary_accept_kind text;
DECLARE prose_accept_kind text;
BEGIN
    SELECT kind, job_id, context_sha INTO summary_kind, summary_job, summary_context
    FROM chronicle.person_history_candidates WHERE candidate_sha = NEW.summary_candidate_sha;
    SELECT kind, job_id, context_sha INTO prose_kind, prose_job, prose_context
    FROM chronicle.person_history_candidates WHERE candidate_sha = NEW.prose_candidate_sha;
    IF summary_kind IS DISTINCT FROM 'summary' OR prose_kind IS DISTINCT FROM 'prose'
       OR summary_job IS DISTINCT FROM NEW.job_id OR prose_job IS DISTINCT FROM NEW.job_id
       OR summary_context IS DISTINCT FROM NEW.context_sha
       OR prose_context IS DISTINCT FROM NEW.context_sha THEN
        RAISE EXCEPTION 'person-history publication candidates do not share job, kind and context';
    END IF;
    IF NOT chronicle.person_history_candidate_is_current(
        NEW.job_id, 'summary', NEW.summary_candidate_sha
    ) OR NOT chronicle.person_history_candidate_is_current(
        NEW.job_id, 'prose', NEW.prose_candidate_sha
    ) THEN
        RAISE EXCEPTION 'person-history publication requires the current candidate frontier';
    END IF;
    SELECT job_id, kind INTO summary_accept_job, summary_accept_kind
    FROM chronicle.person_history_acceptances
    WHERE acceptance_id = NEW.summary_acceptance_id
      AND candidate_sha256 = NEW.summary_candidate_sha
      AND input_sha256 = NEW.context_sha;
    SELECT job_id, kind INTO prose_accept_job, prose_accept_kind
    FROM chronicle.person_history_acceptances
    WHERE acceptance_id = NEW.prose_acceptance_id
      AND candidate_sha256 = NEW.prose_candidate_sha
      AND input_sha256 = NEW.context_sha;
    IF summary_accept_job IS DISTINCT FROM NEW.job_id OR summary_accept_kind IS DISTINCT FROM 'summary'
       OR prose_accept_job IS DISTINCT FROM NEW.job_id OR prose_accept_kind IS DISTINCT FROM 'prose' THEN
        RAISE EXCEPTION 'person-history publication requires accepted summary and prose';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER person_history_publication_guard
    BEFORE INSERT ON chronicle.person_histories
    FOR EACH ROW EXECUTE FUNCTION chronicle.check_person_history_publication();
