-- Chronicle-only derived content. Uses the existing job/review authority.
CREATE TABLE chronicle.narrative_candidates (
    candidate_sha text PRIMARY KEY CHECK (candidate_sha ~ '^[0-9a-f]{64}$'),
    job_id uuid NOT NULL REFERENCES chronicle.ingestion_jobs(job_id),
    kind text NOT NULL CHECK (kind IN ('facts', 'prose')),
    review_id uuid NOT NULL UNIQUE REFERENCES chronicle.review_items(review_id),
    context_sha text NOT NULL CHECK (context_sha ~ '^[0-9a-f]{64}$'),
    context_payload jsonb NOT NULL,
    candidate_payload jsonb NOT NULL,
    model_version text NOT NULL CHECK (model_version <> ''),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, kind)
);

CREATE TABLE chronicle.historical_narratives (
    version_sha text PRIMARY KEY CHECK (version_sha ~ '^[0-9a-f]{64}$'),
    job_id uuid NOT NULL UNIQUE REFERENCES chronicle.ingestion_jobs(job_id),
    catalog_sha text NOT NULL REFERENCES chronicle.canonical_catalogs(artifact_sha256),
    facts_review_id uuid NOT NULL REFERENCES chronicle.review_items(review_id),
    prose_review_id uuid NOT NULL REFERENCES chronicle.review_items(review_id),
    facts_sha text NOT NULL CHECK (facts_sha ~ '^[0-9a-f]{64}$'),
    prose_sha text NOT NULL CHECK (prose_sha ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL,
    publication_sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    published_at timestamptz NOT NULL DEFAULT now(),
    CHECK (facts_review_id <> prose_review_id)
);

CREATE TRIGGER narrative_candidates_immutable BEFORE UPDATE OR DELETE
ON chronicle.narrative_candidates FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_reading_mutation();
CREATE TRIGGER historical_narratives_immutable BEFORE UPDATE OR DELETE
ON chronicle.historical_narratives FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_reading_mutation();

CREATE FUNCTION chronicle.check_narrative_reviews() RETURNS trigger AS $$
DECLARE accepted integer;
BEGIN
    SELECT count(*) INTO accepted
    FROM chronicle.review_items r
    JOIN chronicle.narrative_candidates c ON c.review_id = r.review_id AND c.job_id = r.job_id
    WHERE r.job_id = NEW.job_id AND r.status = 'resolved'
      AND r.payload->>'scope' = 'narrative'
      AND r.payload->'decision'->>'decision' = 'approve'
      AND ((r.review_id = NEW.facts_review_id AND c.kind = 'facts'
            AND r.payload->'decision'->>'content_sha' = NEW.facts_sha)
        OR (r.review_id = NEW.prose_review_id AND c.kind = 'prose'
            AND r.payload->'decision'->>'content_sha' = NEW.prose_sha));
    IF accepted <> 2 THEN
        RAISE EXCEPTION 'historical narrative requires approved facts and prose reviews for the same job';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER historical_narratives_reviews BEFORE INSERT
ON chronicle.historical_narratives FOR EACH ROW EXECUTE FUNCTION chronicle.check_narrative_reviews();
