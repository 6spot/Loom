-- C3-T06: one immutable acceptance boundary for automatic and human paths.
--
-- 0008 deliberately made a ReviewItem mandatory for every narrative
-- candidate.  Automatic acceptance is not a fake ReviewItem, so this
-- migration makes that relationship optional and adds a separate immutable
-- receipt.  Historical publication rows carry both the receipt id and the
-- optional human review id; the trigger below is the only publication gate.

ALTER TABLE chronicle.narrative_candidates
    ALTER COLUMN review_id DROP NOT NULL;

ALTER TABLE chronicle.narrative_candidates
    ADD COLUMN IF NOT EXISTS upstream_candidate_sha text
        CHECK (upstream_candidate_sha IS NULL OR upstream_candidate_sha ~ '^[0-9a-f]{64}$');

-- A human revision is an append-only new candidate, never an UPDATE to the
-- model draft.  Revision zero remains the 0008 row; these rows form the
-- current candidate frontier for the same job/kind.
CREATE TABLE IF NOT EXISTS chronicle.narrative_candidate_versions (
    candidate_sha text PRIMARY KEY CHECK (candidate_sha ~ '^[0-9a-f]{64}$'),
    job_id uuid NOT NULL REFERENCES chronicle.ingestion_jobs(job_id),
    kind text NOT NULL CHECK (kind IN ('facts', 'prose')),
    review_id uuid UNIQUE REFERENCES chronicle.review_items(review_id),
    parent_candidate_sha text NOT NULL CHECK (parent_candidate_sha ~ '^[0-9a-f]{64}$'),
    revision_no integer NOT NULL CHECK (revision_no >= 1),
    upstream_candidate_sha text
        CHECK (upstream_candidate_sha IS NULL OR upstream_candidate_sha ~ '^[0-9a-f]{64}$'),
    context_sha text NOT NULL CHECK (context_sha ~ '^[0-9a-f]{64}$'),
    context_payload jsonb NOT NULL,
    candidate_payload jsonb NOT NULL,
    model_version text NOT NULL CHECK (model_version <> ''),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, kind, revision_no)
);

CREATE INDEX IF NOT EXISTS narrative_candidate_versions_frontier_idx
    ON chronicle.narrative_candidate_versions(job_id, kind, revision_no DESC);

CREATE TABLE IF NOT EXISTS chronicle.narrative_acceptances (
    acceptance_id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES chronicle.ingestion_jobs(job_id),
    kind text NOT NULL CHECK (kind IN ('facts', 'prose')),
    acceptance_type text NOT NULL
        CHECK (acceptance_type IN ('human', 'policy_model_review')),
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
    review_id uuid UNIQUE REFERENCES chronicle.review_items(review_id),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, kind, candidate_sha256),
    CHECK (
        (acceptance_type = 'human' AND review_id IS NOT NULL)
        OR (acceptance_type = 'policy_model_review' AND review_id IS NULL)
    ),
    CHECK (draft_sha256 = content_sha256)
);

CREATE INDEX IF NOT EXISTS narrative_acceptances_job_kind_idx
    ON chronicle.narrative_acceptances(job_id, kind, created_at DESC);

ALTER TABLE chronicle.historical_narratives
    ALTER COLUMN facts_review_id DROP NOT NULL,
    ALTER COLUMN prose_review_id DROP NOT NULL;

ALTER TABLE chronicle.historical_narratives
    ADD COLUMN IF NOT EXISTS facts_acceptance_id uuid
        REFERENCES chronicle.narrative_acceptances(acceptance_id),
    ADD COLUMN IF NOT EXISTS prose_acceptance_id uuid
        REFERENCES chronicle.narrative_acceptances(acceptance_id);

CREATE TRIGGER narrative_candidate_versions_immutable BEFORE UPDATE OR DELETE
ON chronicle.narrative_candidate_versions FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_reading_mutation();
CREATE TRIGGER narrative_acceptances_immutable BEFORE UPDATE OR DELETE
ON chronicle.narrative_acceptances FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_reading_mutation();

CREATE OR REPLACE FUNCTION chronicle.narrative_candidate_is_current(
    p_job_id uuid, p_kind text, p_candidate_sha text
) RETURNS boolean AS $$
DECLARE current_sha text;
BEGIN
    SELECT candidate_sha INTO current_sha
    FROM (
        SELECT candidate_sha, 0 AS revision_no
        FROM chronicle.narrative_candidates
        WHERE job_id = p_job_id AND kind = p_kind
        UNION ALL
        SELECT candidate_sha, revision_no
        FROM chronicle.narrative_candidate_versions
        WHERE job_id = p_job_id AND kind = p_kind
    ) candidates
    ORDER BY revision_no DESC, candidate_sha DESC
    LIMIT 1;
    RETURN current_sha IS NOT NULL AND current_sha = p_candidate_sha;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION chronicle.check_narrative_candidate_version()
RETURNS trigger AS $$
DECLARE
    expected_revision integer;
    parent_context_sha text;
BEGIN
    IF NOT chronicle.narrative_candidate_is_current(
        NEW.job_id, NEW.kind, NEW.parent_candidate_sha
    ) THEN
        RAISE EXCEPTION 'narrative revision parent is not the current candidate frontier';
    END IF;
    SELECT coalesce(max(revision_no), 0) + 1 INTO expected_revision
    FROM chronicle.narrative_candidate_versions
    WHERE job_id = NEW.job_id AND kind = NEW.kind;
    IF NEW.revision_no <> expected_revision THEN
        RAISE EXCEPTION 'narrative revision number is not the next append-only version';
    END IF;
    SELECT context_sha INTO parent_context_sha
    FROM (
        SELECT candidate_sha, context_sha, 0 AS revision_no
        FROM chronicle.narrative_candidates
        WHERE job_id = NEW.job_id AND kind = NEW.kind
        UNION ALL
        SELECT candidate_sha, context_sha, revision_no
        FROM chronicle.narrative_candidate_versions
        WHERE job_id = NEW.job_id AND kind = NEW.kind
    ) candidates
    WHERE candidate_sha = NEW.parent_candidate_sha
    ORDER BY revision_no DESC
    LIMIT 1;
    IF parent_context_sha IS DISTINCT FROM NEW.context_sha THEN
        RAISE EXCEPTION 'narrative revision changed its frozen input context';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER narrative_candidate_version_guard BEFORE INSERT
ON chronicle.narrative_candidate_versions FOR EACH ROW EXECUTE FUNCTION chronicle.check_narrative_candidate_version();

CREATE OR REPLACE FUNCTION chronicle.check_narrative_acceptance()
RETURNS trigger AS $$
DECLARE
    candidate_context_sha text;
    plan_payload jsonb;
BEGIN
    IF NEW.acceptance_type = 'human' THEN
        IF NOT EXISTS (
            SELECT 1
            FROM chronicle.review_items r
            WHERE r.review_id = NEW.review_id
              AND r.job_id = NEW.job_id
              AND r.status = 'resolved'
              AND r.payload->>'scope' = 'narrative'
              AND r.payload->>'narrative_kind' = NEW.kind
              AND r.payload->'decision'->>'decision' = 'approve'
              AND r.payload->'decision'->>'candidate_sha' = NEW.candidate_sha256
              AND r.payload->'decision'->>'content_sha' = NEW.content_sha256
        ) THEN
            RAISE EXCEPTION 'human narrative acceptance is not bound to a resolved approval for the exact candidate';
        END IF;
    ELSE
        IF NEW.review_id IS NOT NULL THEN
            RAISE EXCEPTION 'automatic narrative acceptance cannot carry a human review';
        END IF;
        IF NEW.pipeline_fingerprint IS NULL OR NEW.pipeline_fingerprint = '' THEN
            RAISE EXCEPTION 'automatic narrative acceptance requires a frozen pipeline fingerprint';
        END IF;
        IF coalesce(array_length(NEW.model_output_sha256s, 1), 0) = 0 THEN
            RAISE EXCEPTION 'automatic narrative acceptance requires completed model outputs';
        END IF;
        SELECT payload INTO plan_payload
        FROM chronicle.ingestion_outputs
        WHERE job_id = NEW.job_id
          AND artifact_type = 'narrative-plan'
          AND payload->>'pipeline_fingerprint' = NEW.pipeline_fingerprint
          AND payload->>'context_sha256' = NEW.input_sha256;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'automatic narrative acceptance has no matching frozen narrative plan';
        END IF;
        IF jsonb_array_length(
               plan_payload->'config'->'steps'->(NEW.kind || '_generate')
           ) <> coalesce(array_length(NEW.model_output_sha256s, 1), 0) THEN
            RAISE EXCEPTION 'automatic narrative acceptance does not include every configured model output';
        END IF;
        IF coalesce(array_length(NEW.model_output_sha256s, 1), 0) > 1
           AND jsonb_array_length(
                   plan_payload->'config'->'steps'->(NEW.kind || '_compare')
               ) <> coalesce(array_length(NEW.model_opinion_sha256s, 1), 0) THEN
            RAISE EXCEPTION 'automatic narrative acceptance does not include every configured model opinion';
        END IF;
        IF coalesce(array_length(NEW.model_output_sha256s, 1), 0) = 1
           AND coalesce(array_length(NEW.model_opinion_sha256s, 1), 0) <> 0 THEN
            RAISE EXCEPTION 'automatic narrative acceptance has unexpected model opinions for one candidate';
        END IF;
        IF EXISTS (
            SELECT 1
            FROM unnest(NEW.model_output_sha256s) output_sha
            WHERE NOT EXISTS (
                SELECT 1
                FROM chronicle.ingestion_outputs o
                WHERE o.job_id = NEW.job_id
                  AND o.artifact_type = 'narrative-step'
                  AND o.artifact_sha256 = output_sha
                  AND o.payload->>'status' = 'completed'
                  AND o.payload->>'step' = CASE
                      WHEN NEW.kind = 'facts' THEN 'facts_generate' ELSE 'prose_generate' END
                  AND o.payload->>'pipeline_fingerprint' = NEW.pipeline_fingerprint
                  AND o.payload->>'context_sha256' = NEW.input_sha256
            )
        ) THEN
            RAISE EXCEPTION 'automatic narrative acceptance references a missing or incomplete model result';
        END IF;
        IF EXISTS (
            SELECT 1
            FROM unnest(NEW.model_opinion_sha256s) output_sha
            WHERE NOT EXISTS (
                SELECT 1
                FROM chronicle.ingestion_outputs o
                WHERE o.job_id = NEW.job_id
                  AND o.artifact_type = 'narrative-step'
                  AND o.artifact_sha256 = output_sha
                  AND o.payload->>'status' = 'completed'
                  AND o.payload->>'step' = CASE
                      WHEN NEW.kind = 'facts' THEN 'facts_compare' ELSE 'prose_compare' END
                  AND o.payload->>'pipeline_fingerprint' = NEW.pipeline_fingerprint
                  AND o.payload->>'context_sha256' = NEW.input_sha256
            )
        ) THEN
            RAISE EXCEPTION 'automatic narrative acceptance references a missing or incomplete model opinion';
        END IF;
    END IF;

    IF NOT chronicle.narrative_candidate_is_current(
        NEW.job_id, NEW.kind, NEW.candidate_sha256
    ) THEN
        RAISE EXCEPTION 'narrative acceptance must bind the current candidate frontier';
    END IF;

    SELECT context_sha INTO candidate_context_sha
    FROM (
        SELECT candidate_sha, context_sha, 0 AS revision_no
        FROM chronicle.narrative_candidates
        WHERE job_id = NEW.job_id AND kind = NEW.kind
        UNION ALL
        SELECT candidate_sha, context_sha, revision_no
        FROM chronicle.narrative_candidate_versions
        WHERE job_id = NEW.job_id AND kind = NEW.kind
    ) candidates
    WHERE candidate_sha = NEW.candidate_sha256
    ORDER BY revision_no DESC
    LIMIT 1;
    IF candidate_context_sha IS DISTINCT FROM NEW.input_sha256 THEN
        RAISE EXCEPTION 'narrative acceptance input hash does not match the candidate context';
    END IF;
    IF NEW.payload->>'schema' IS DISTINCT FROM 'chronicle.narrative-acceptance'
       OR NEW.payload->>'version' IS DISTINCT FROM '0.1'
       OR NEW.payload->>'acceptance_type' IS DISTINCT FROM NEW.acceptance_type
       OR NEW.payload->>'job_id' IS DISTINCT FROM NEW.job_id::text
       OR NEW.payload->>'kind' IS DISTINCT FROM NEW.kind
       OR NEW.payload->>'policy_version' IS DISTINCT FROM NEW.policy_version
       OR NEW.payload->>'input_sha256' IS DISTINCT FROM NEW.input_sha256
       OR NEW.payload->>'candidate_sha256' IS DISTINCT FROM NEW.candidate_sha256
       OR NEW.payload->>'draft_sha256' IS DISTINCT FROM NEW.draft_sha256
       OR NEW.payload->>'content_sha256' IS DISTINCT FROM NEW.content_sha256
       OR NEW.payload->>'pipeline_fingerprint' IS DISTINCT FROM NEW.pipeline_fingerprint THEN
        RAISE EXCEPTION 'narrative acceptance payload is not self-consistent';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS narrative_acceptance_guard ON chronicle.narrative_acceptances;
CREATE TRIGGER narrative_acceptance_guard BEFORE INSERT
ON chronicle.narrative_acceptances FOR EACH ROW EXECUTE FUNCTION chronicle.check_narrative_acceptance();

-- Keep the historical trigger name used by the old schema, but replace its
-- implementation: neither automatic publication nor human publication has a
-- second acceptance path now.
CREATE OR REPLACE FUNCTION chronicle.check_narrative_reviews() RETURNS trigger AS $$
DECLARE
    facts_accept chronicle.narrative_acceptances%ROWTYPE;
    prose_accept chronicle.narrative_acceptances%ROWTYPE;
BEGIN
    IF NEW.facts_acceptance_id IS NULL OR NEW.prose_acceptance_id IS NULL THEN
        RAISE EXCEPTION 'historical narrative requires one valid facts and prose acceptance receipt';
    END IF;

    SELECT * INTO facts_accept
    FROM chronicle.narrative_acceptances
    WHERE acceptance_id = NEW.facts_acceptance_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'historical narrative facts acceptance does not exist';
    END IF;
    SELECT * INTO prose_accept
    FROM chronicle.narrative_acceptances
    WHERE acceptance_id = NEW.prose_acceptance_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'historical narrative prose acceptance does not exist';
    END IF;

    IF facts_accept.acceptance_id = prose_accept.acceptance_id
       OR facts_accept.job_id IS DISTINCT FROM NEW.job_id
       OR prose_accept.job_id IS DISTINCT FROM NEW.job_id
       OR facts_accept.kind <> 'facts'
       OR prose_accept.kind <> 'prose'
       OR facts_accept.content_sha256 IS DISTINCT FROM NEW.facts_sha
       OR prose_accept.content_sha256 IS DISTINCT FROM NEW.prose_sha
       OR facts_accept.review_id IS DISTINCT FROM NEW.facts_review_id
       OR prose_accept.review_id IS DISTINCT FROM NEW.prose_review_id
       OR NOT chronicle.narrative_candidate_is_current(
            NEW.job_id, 'facts', facts_accept.candidate_sha256
       )
       OR NOT chronicle.narrative_candidate_is_current(
            NEW.job_id, 'prose', prose_accept.candidate_sha256
       ) THEN
        RAISE EXCEPTION 'historical narrative acceptance receipts are not bound to the current job candidates';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS historical_narratives_reviews ON chronicle.historical_narratives;
CREATE TRIGGER historical_narratives_reviews BEFORE INSERT
ON chronicle.historical_narratives FOR EACH ROW EXECUTE FUNCTION chronicle.check_narrative_reviews();
