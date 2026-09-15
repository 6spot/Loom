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

-- Python persists hashes over canonical JSON (sorted keys, compact separators,
-- and UTF-8).  jsonb::text is neither key-sorted nor compact, so the
-- acceptance boundary must use the same canonical bytes before recomputing a
-- candidate or receipt digest.  Narrative candidates only admit integer
-- numbers; their string/boolean/null representation is shared by PostgreSQL's
-- JSON encoder and Python's ensure_ascii=False encoder.
CREATE OR REPLACE FUNCTION chronicle.canonical_jsonb(p_value jsonb)
RETURNS text AS $$
DECLARE
    result text;
    item record;
    first_item boolean := true;
BEGIN
    CASE jsonb_typeof(p_value)
        WHEN 'object' THEN
            result := '{';
            FOR item IN
                SELECT key, value
                FROM jsonb_each(p_value)
                ORDER BY key COLLATE "C"
            LOOP
                IF NOT first_item THEN
                    result := result || ',';
                END IF;
                result := result || to_json(item.key)::text || ':'
                    || chronicle.canonical_jsonb(item.value);
                first_item := false;
            END LOOP;
            RETURN result || '}';
        WHEN 'array' THEN
            result := '[';
            FOR item IN
                SELECT value
                FROM jsonb_array_elements(p_value) WITH ORDINALITY AS entries(value, ordinal)
                ORDER BY ordinal
            LOOP
                IF NOT first_item THEN
                    result := result || ',';
                END IF;
                result := result || chronicle.canonical_jsonb(item.value);
                first_item := false;
            END LOOP;
            RETURN result || ']';
        WHEN 'string' THEN
            RETURN to_json(p_value #>> '{}')::text;
        WHEN 'number' THEN
            RETURN p_value::text;
        WHEN 'boolean' THEN
            RETURN p_value::text;
        WHEN 'null' THEN
            RETURN 'null';
        ELSE
            RAISE EXCEPTION 'unsupported canonical JSONB type %', jsonb_typeof(p_value);
    END CASE;
END;
$$ LANGUAGE plpgsql IMMUTABLE STRICT;

CREATE OR REPLACE FUNCTION chronicle.jsonb_sha256(p_value jsonb)
RETURNS text AS $$
    SELECT encode(
        pg_catalog.sha256(convert_to(chronicle.canonical_jsonb($1), 'UTF8')),
        'hex'
    )
$$ LANGUAGE sql IMMUTABLE STRICT;

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
    candidate_context_payload jsonb;
    candidate_payload jsonb;
    candidate_review_id uuid;
    candidate_upstream_candidate_sha text;
    candidate_parent_candidate_sha text;
    candidate_revision_no integer;
    candidate_digest text;
    candidate_content_sha text;
    plan_payload jsonb;
    plan_artifact_sha text;
    receipt_keys text[] := ARRAY[
        'acceptance_type', 'candidate_sha256', 'content_sha256', 'created_at',
        'decision', 'decision_reason', 'draft_sha256', 'input_sha256', 'job_id',
        'kind', 'model_opinion_sha256s', 'model_output_sha256s',
        'pipeline_fingerprint', 'policy_version', 'receipt_sha256', 'review_id',
        'schema', 'version'
    ]::text[];
    review_payload jsonb;
    generation_step text;
    comparison_step text;
    expected_generation_count integer;
    expected_comparison_count integer;
    generation_count integer;
    comparison_count integer;
    generation_sha text;
    comparison_sha text;
    output_artifact_sha text;
    output_payload jsonb;
    output_parsed jsonb;
    output_slot text;
    candidate_set jsonb := '[]'::jsonb;
    candidate_set_sha text;
    matched_generation_count integer := 0;
    generation_slots_seen text[] := ARRAY[]::text[];
    comparison_slots_seen text[] := ARRAY[]::text[];
    selected_sha text;
    first_selected_sha text;
BEGIN
    IF jsonb_typeof(NEW.payload) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'narrative acceptance receipt must be a JSON object';
    END IF;
    IF (
        SELECT array_agg(keys.key ORDER BY keys.key COLLATE "C")
        FROM jsonb_object_keys(NEW.payload) AS keys(key)
    ) IS DISTINCT FROM receipt_keys THEN
        RAISE EXCEPTION 'narrative acceptance receipt has an incomplete or unexpected field set';
    END IF;
    IF NEW.payload->>'receipt_sha256' IS NULL
       OR NEW.payload->>'receipt_sha256' !~ '^[0-9a-f]{64}$'
       OR chronicle.jsonb_sha256(NEW.payload - 'receipt_sha256') IS DISTINCT FROM NEW.payload->>'receipt_sha256' THEN
        RAISE EXCEPTION 'narrative acceptance receipt digest is invalid';
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
       OR COALESCE(NEW.payload->'pipeline_fingerprint', 'null'::jsonb)
            IS DISTINCT FROM COALESCE(to_jsonb(NEW.pipeline_fingerprint), 'null'::jsonb)
       OR COALESCE(NEW.payload->'model_output_sha256s', 'null'::jsonb)
            IS DISTINCT FROM to_jsonb(NEW.model_output_sha256s)
       OR COALESCE(NEW.payload->'model_opinion_sha256s', 'null'::jsonb)
            IS DISTINCT FROM to_jsonb(NEW.model_opinion_sha256s)
       OR NEW.payload->>'decision' IS DISTINCT FROM NEW.decision
       OR NEW.payload->>'decision_reason' IS DISTINCT FROM NEW.decision_reason
       OR COALESCE(NEW.payload->'review_id', 'null'::jsonb)
            IS DISTINCT FROM COALESCE(to_jsonb(NEW.review_id), 'null'::jsonb) THEN
        RAISE EXCEPTION 'narrative acceptance receipt fields do not match the relational acceptance';
    END IF;
    IF NEW.payload->>'created_at' IS NULL OR btrim(NEW.payload->>'created_at') = '' THEN
        RAISE EXCEPTION 'narrative acceptance receipt has no creation time';
    END IF;
    BEGIN
        PERFORM (NEW.payload->>'created_at')::timestamptz;
    EXCEPTION WHEN others THEN
        RAISE EXCEPTION 'narrative acceptance receipt creation time is invalid';
    END;
    IF EXISTS (
        SELECT 1
        FROM unnest(NEW.model_output_sha256s) AS hashes(value)
        WHERE value IS NULL OR value !~ '^[0-9a-f]{64}$'
    ) OR (
        SELECT count(*) <> count(DISTINCT value)
        FROM unnest(NEW.model_output_sha256s) AS hashes(value)
    ) THEN
        RAISE EXCEPTION 'narrative acceptance model output hashes are invalid or duplicated';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM unnest(NEW.model_opinion_sha256s) AS hashes(value)
        WHERE value IS NULL OR value !~ '^[0-9a-f]{64}$'
    ) OR (
        SELECT count(*) <> count(DISTINCT value)
        FROM unnest(NEW.model_opinion_sha256s) AS hashes(value)
    ) THEN
        RAISE EXCEPTION 'narrative acceptance model opinion hashes are invalid or duplicated';
    END IF;

    SELECT candidates.context_sha, candidates.context_payload, candidates.candidate_payload,
           candidates.review_id, candidates.upstream_candidate_sha,
           candidates.parent_candidate_sha, candidates.revision_no
    INTO candidate_context_sha, candidate_context_payload, candidate_payload,
         candidate_review_id, candidate_upstream_candidate_sha,
         candidate_parent_candidate_sha, candidate_revision_no
    FROM (
        SELECT c.job_id, c.kind, c.candidate_sha, c.context_sha, c.context_payload,
               c.candidate_payload, c.review_id, c.upstream_candidate_sha,
               NULL::text AS parent_candidate_sha, 0::integer AS revision_no
        FROM chronicle.narrative_candidates c
        UNION ALL
        SELECT v.job_id, v.kind, v.candidate_sha, v.context_sha, v.context_payload,
               v.candidate_payload, v.review_id, v.upstream_candidate_sha,
               v.parent_candidate_sha, v.revision_no
        FROM chronicle.narrative_candidate_versions v
    ) candidates
    WHERE candidates.job_id = NEW.job_id
      AND candidates.kind = NEW.kind
      AND candidates.candidate_sha = NEW.candidate_sha256
    ORDER BY candidates.revision_no DESC
    LIMIT 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'narrative acceptance candidate does not exist';
    END IF;
    IF NOT chronicle.narrative_candidate_is_current(
        NEW.job_id, NEW.kind, NEW.candidate_sha256
    ) THEN
        RAISE EXCEPTION 'narrative acceptance must bind the current candidate frontier';
    END IF;
    IF jsonb_typeof(candidate_context_payload) IS DISTINCT FROM 'object'
       OR jsonb_typeof(candidate_payload) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'narrative candidate payloads must be JSON objects';
    END IF;
    IF chronicle.jsonb_sha256(candidate_context_payload) IS DISTINCT FROM candidate_context_sha THEN
        RAISE EXCEPTION 'narrative candidate context hash does not match its payload';
    END IF;
    IF candidate_revision_no = 0 THEN
        candidate_digest := chronicle.jsonb_sha256(jsonb_build_object(
            'job_id', NEW.job_id::text,
            'kind', NEW.kind,
            'context', candidate_context_payload,
            'candidate', candidate_payload,
            'upstream_candidate_sha', candidate_upstream_candidate_sha
        ));
    ELSE
        candidate_digest := chronicle.jsonb_sha256(jsonb_build_object(
            'job_id', NEW.job_id::text,
            'kind', NEW.kind,
            'context', candidate_context_payload,
            'candidate', candidate_payload,
            'parent_candidate_sha', candidate_parent_candidate_sha,
            'revision_no', candidate_revision_no,
            'upstream_candidate_sha', candidate_upstream_candidate_sha
        ));
    END IF;
    IF candidate_digest IS DISTINCT FROM NEW.candidate_sha256 THEN
        RAISE EXCEPTION 'narrative candidate digest does not match its current revision payload';
    END IF;
    candidate_content_sha := chronicle.jsonb_sha256(candidate_payload);
    IF NEW.draft_sha256 IS DISTINCT FROM candidate_content_sha
       OR NEW.content_sha256 IS DISTINCT FROM candidate_content_sha THEN
        RAISE EXCEPTION 'narrative acceptance draft/content hash is not derived from the current candidate payload';
    END IF;
    IF candidate_context_sha IS DISTINCT FROM NEW.input_sha256 THEN
        RAISE EXCEPTION 'narrative acceptance input hash does not match the candidate context';
    END IF;

    IF NEW.acceptance_type = 'human' THEN
        IF candidate_review_id IS DISTINCT FROM NEW.review_id THEN
            RAISE EXCEPTION 'human narrative acceptance is not bound to the candidate revision review';
        END IF;
        SELECT r.payload INTO review_payload
        FROM chronicle.review_items r
        WHERE r.review_id = NEW.review_id
          AND r.job_id = NEW.job_id
          AND r.kind = 'stage_gate'
          AND r.status = 'resolved';
        IF NOT FOUND OR jsonb_typeof(review_payload) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'human narrative acceptance is not bound to a resolved review';
        END IF;
        IF review_payload->>'scope' IS DISTINCT FROM 'narrative'
           OR review_payload->>'stage' IS DISTINCT FROM 'present'
           OR review_payload->>'narrative_kind' IS DISTINCT FROM NEW.kind
           OR review_payload->>'candidate_sha' IS DISTINCT FROM NEW.candidate_sha256
           OR (
                review_payload ? 'context_sha256'
                AND review_payload->>'context_sha256' IS DISTINCT FROM NEW.input_sha256
           )
           OR COALESCE(review_payload->'upstream_candidate_sha', 'null'::jsonb)
                IS DISTINCT FROM COALESCE(to_jsonb(candidate_upstream_candidate_sha), 'null'::jsonb)
           OR jsonb_typeof(review_payload->'decision') IS DISTINCT FROM 'object'
           OR review_payload->'decision'->>'decision' IS DISTINCT FROM 'approve'
           OR review_payload->'decision'->>'candidate_sha' IS DISTINCT FROM NEW.candidate_sha256
           OR review_payload->'decision'->>'content_sha' IS DISTINCT FROM candidate_content_sha
           OR review_payload->'decision'->'content' IS DISTINCT FROM candidate_payload
           OR review_payload->'decision'->>'rationale' IS DISTINCT FROM NEW.decision_reason THEN
            RAISE EXCEPTION 'human narrative acceptance receipt is not bound to the complete corresponding review';
        END IF;
    ELSIF NEW.acceptance_type = 'policy_model_review' THEN
        IF NEW.review_id IS NOT NULL THEN
            RAISE EXCEPTION 'automatic narrative acceptance cannot carry a human review';
        END IF;
        IF candidate_review_id IS NOT NULL THEN
            RAISE EXCEPTION 'automatic narrative acceptance cannot bind a human candidate review';
        END IF;
        IF NEW.pipeline_fingerprint IS NULL OR NEW.pipeline_fingerprint = '' THEN
            RAISE EXCEPTION 'automatic narrative acceptance requires a frozen pipeline fingerprint';
        END IF;
        IF coalesce(array_length(NEW.model_output_sha256s, 1), 0) = 0 THEN
            RAISE EXCEPTION 'automatic narrative acceptance requires completed model outputs';
        END IF;
        SELECT o.artifact_sha256, o.payload
        INTO plan_artifact_sha, plan_payload
        FROM chronicle.ingestion_outputs o
        WHERE o.job_id = NEW.job_id
          AND o.artifact_type = 'narrative-plan'
          AND o.payload->>'pipeline_fingerprint' = NEW.pipeline_fingerprint
          AND o.payload->>'context_sha256' = NEW.input_sha256
        ORDER BY o.created_at DESC, o.output_id DESC
        LIMIT 1;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'automatic narrative acceptance has no matching frozen narrative plan';
        END IF;
        IF plan_artifact_sha IS DISTINCT FROM chronicle.jsonb_sha256(plan_payload)
           OR plan_payload->>'schema' IS DISTINCT FROM 'chronicle.narrative-plan'
           OR plan_payload->>'version' IS DISTINCT FROM '0.1'
           OR plan_payload->>'status' IS DISTINCT FROM 'frozen'
           OR jsonb_typeof(plan_payload->'context') IS DISTINCT FROM 'object'
           OR plan_payload->'context' IS DISTINCT FROM candidate_context_payload
           OR chronicle.jsonb_sha256(plan_payload->'context') IS DISTINCT FROM NEW.input_sha256
           OR chronicle.jsonb_sha256(jsonb_build_object(
                'context', plan_payload->'context', 'config', plan_payload->'config'
              )) IS DISTINCT FROM NEW.pipeline_fingerprint
           OR jsonb_typeof(plan_payload->'config') IS DISTINCT FROM 'object'
           OR jsonb_typeof(plan_payload->'config'->'steps') IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'automatic narrative acceptance plan is not a complete frozen plan';
        END IF;
        generation_step := NEW.kind || '_generate';
        comparison_step := NEW.kind || '_compare';
        IF jsonb_typeof(plan_payload->'config'->'steps'->generation_step) IS DISTINCT FROM 'array' THEN
            RAISE EXCEPTION 'automatic narrative acceptance plan has no generation slots';
        END IF;
        expected_generation_count := jsonb_array_length(plan_payload->'config'->'steps'->generation_step);
        generation_count := cardinality(NEW.model_output_sha256s);
        IF expected_generation_count <> generation_count THEN
            RAISE EXCEPTION 'automatic narrative acceptance does not include every configured model output';
        END IF;
        IF generation_count > 1 THEN
            IF jsonb_typeof(plan_payload->'config'->'steps'->comparison_step) IS DISTINCT FROM 'array' THEN
                RAISE EXCEPTION 'automatic narrative acceptance plan has no comparison slots';
            END IF;
            expected_comparison_count := jsonb_array_length(plan_payload->'config'->'steps'->comparison_step);
            comparison_count := cardinality(NEW.model_opinion_sha256s);
            IF expected_comparison_count <> comparison_count THEN
                RAISE EXCEPTION 'automatic narrative acceptance does not include every configured model opinion';
            END IF;
        ELSIF cardinality(NEW.model_opinion_sha256s) <> 0 THEN
            RAISE EXCEPTION 'automatic narrative acceptance has unexpected model opinions for one candidate';
        END IF;

        FOREACH generation_sha IN ARRAY NEW.model_output_sha256s LOOP
            SELECT o.artifact_sha256, o.payload
            INTO output_artifact_sha, output_payload
            FROM chronicle.ingestion_outputs o
            WHERE o.job_id = NEW.job_id
              AND o.artifact_type = 'narrative-step'
              AND o.artifact_sha256 = generation_sha;
            IF NOT FOUND
               OR output_artifact_sha IS DISTINCT FROM chronicle.jsonb_sha256(output_payload) THEN
                RAISE EXCEPTION 'automatic narrative acceptance references a forged or missing model result';
            END IF;
            IF output_payload->>'schema' IS DISTINCT FROM 'chronicle.narrative-step'
               OR output_payload->>'version' IS DISTINCT FROM '0.1'
               OR output_payload->>'status' IS DISTINCT FROM 'completed'
               OR output_payload->>'step' IS DISTINCT FROM generation_step
               OR output_payload->>'pipeline_fingerprint' IS DISTINCT FROM NEW.pipeline_fingerprint
               OR output_payload->>'context_sha256' IS DISTINCT FROM NEW.input_sha256
               OR output_payload->>'model' IS NULL
               OR btrim(output_payload->>'model') = ''
               OR output_payload->>'slot' IS NULL
               OR btrim(output_payload->>'slot') = ''
               OR jsonb_typeof(output_payload->'parsed') IS DISTINCT FROM 'object' THEN
                RAISE EXCEPTION 'automatic narrative acceptance references an incomplete model result';
            END IF;
            output_slot := output_payload->>'slot';
            IF output_slot = ANY(generation_slots_seen) THEN
                RAISE EXCEPTION 'automatic narrative acceptance repeats a model generation slot';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(plan_payload->'config'->'steps'->generation_step) AS slots(slot)
                WHERE slots.slot = output_slot
            ) THEN
                RAISE EXCEPTION 'automatic narrative acceptance references an unconfigured model generation slot';
            END IF;
            generation_slots_seen := array_append(generation_slots_seen, output_slot);
            candidate_set := candidate_set || jsonb_build_array(jsonb_build_object(
                'candidate_sha256', generation_sha,
                'model', output_payload->>'model',
                'content', output_payload->'parsed'
            ));
            IF output_payload->'parsed' IS NOT DISTINCT FROM candidate_payload THEN
                matched_generation_count := matched_generation_count + 1;
            END IF;
        END LOOP;
        IF matched_generation_count = 0 THEN
            RAISE EXCEPTION 'automatic narrative acceptance model outputs do not produce the current candidate payload';
        END IF;
        candidate_set_sha := chronicle.jsonb_sha256(candidate_set);

        IF generation_count > 1 THEN
            FOREACH comparison_sha IN ARRAY NEW.model_opinion_sha256s LOOP
                SELECT o.artifact_sha256, o.payload
                INTO output_artifact_sha, output_payload
                FROM chronicle.ingestion_outputs o
                WHERE o.job_id = NEW.job_id
                  AND o.artifact_type = 'narrative-step'
                  AND o.artifact_sha256 = comparison_sha;
                IF NOT FOUND
                   OR output_artifact_sha IS DISTINCT FROM chronicle.jsonb_sha256(output_payload) THEN
                    RAISE EXCEPTION 'automatic narrative acceptance references a forged or missing model opinion';
                END IF;
                IF output_payload->>'schema' IS DISTINCT FROM 'chronicle.narrative-step'
                   OR output_payload->>'version' IS DISTINCT FROM '0.1'
                   OR output_payload->>'status' IS DISTINCT FROM 'completed'
                   OR output_payload->>'step' IS DISTINCT FROM comparison_step
                   OR output_payload->>'pipeline_fingerprint' IS DISTINCT FROM NEW.pipeline_fingerprint
                   OR output_payload->>'context_sha256' IS DISTINCT FROM NEW.input_sha256
                   OR output_payload->>'slot' IS NULL
                   OR btrim(output_payload->>'slot') = ''
                   OR jsonb_typeof(output_payload->'parsed') IS DISTINCT FROM 'object' THEN
                    RAISE EXCEPTION 'automatic narrative acceptance references an incomplete model opinion';
                END IF;
                output_slot := output_payload->>'slot';
                IF output_slot = ANY(comparison_slots_seen) THEN
                    RAISE EXCEPTION 'automatic narrative acceptance repeats a model comparison slot';
                END IF;
                IF NOT EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements_text(plan_payload->'config'->'steps'->comparison_step) AS slots(slot)
                    WHERE slots.slot = output_slot
                ) THEN
                    RAISE EXCEPTION 'automatic narrative acceptance references an unconfigured model comparison slot';
                END IF;
                comparison_slots_seen := array_append(comparison_slots_seen, output_slot);
                output_parsed := output_payload->'parsed';
                IF output_parsed->>'candidate_set_sha256' IS DISTINCT FROM candidate_set_sha THEN
                    RAISE EXCEPTION 'automatic narrative acceptance model opinion is for a different candidate set';
                END IF;
                selected_sha := output_parsed->>'selected_sha256';
                IF selected_sha IS NULL OR NOT (selected_sha = ANY(NEW.model_output_sha256s)) THEN
                    RAISE EXCEPTION 'automatic narrative acceptance model opinion selects an unknown candidate';
                END IF;
                IF first_selected_sha IS NULL THEN
                    first_selected_sha := selected_sha;
                ELSIF first_selected_sha IS DISTINCT FROM selected_sha THEN
                    RAISE EXCEPTION 'automatic narrative acceptance model opinions disagree on the selected candidate';
                END IF;
                IF output_parsed ? 'disagreements' THEN
                    IF jsonb_typeof(output_parsed->'disagreements') IS DISTINCT FROM 'array'
                       OR jsonb_array_length(output_parsed->'disagreements') <> 0 THEN
                        RAISE EXCEPTION 'automatic narrative acceptance has unresolved model disagreements';
                    END IF;
                END IF;
                IF output_parsed ? 'differences' THEN
                    IF jsonb_typeof(output_parsed->'differences') IS DISTINCT FROM 'array' THEN
                        RAISE EXCEPTION 'automatic narrative acceptance model opinion has invalid differences';
                    END IF;
                    IF EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements(output_parsed->'differences') AS differences(value)
                        WHERE differences.value->>'assessment' = 'disputed'
                    ) THEN
                        RAISE EXCEPTION 'automatic narrative acceptance has a disputed model comparison';
                    END IF;
                END IF;
            END LOOP;
            IF first_selected_sha IS NULL THEN
                RAISE EXCEPTION 'automatic narrative acceptance has no selected model candidate';
            END IF;
            SELECT o.payload INTO output_payload
            FROM chronicle.ingestion_outputs o
            WHERE o.job_id = NEW.job_id
              AND o.artifact_type = 'narrative-step'
              AND o.artifact_sha256 = first_selected_sha;
            IF NOT FOUND OR output_payload->'parsed' IS DISTINCT FROM candidate_payload THEN
                RAISE EXCEPTION 'automatic narrative acceptance selected model output is not the current candidate';
            END IF;
        END IF;
    ELSE
        RAISE EXCEPTION 'narrative acceptance type is invalid';
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
