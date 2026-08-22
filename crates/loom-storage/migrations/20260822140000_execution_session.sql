-- Execution Session records are Platform History/provenance. They do not
-- append World Events, advance World Time or mutate a World Runtime Binding.
-- The complete immutable assembly is retained as JSONB for restart/audit;
-- duplicated identity/lifecycle columns provide stable operator predicates.

CREATE TABLE loom_execution_session (
    session_id UUID PRIMARY KEY,
    world_id UUID NOT NULL,
    timeline_id UUID NOT NULL,
    origin TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('Started', 'Committed', 'Rejected', 'Failed')),
    started_at BIGINT NOT NULL,
    ended_at BIGINT,
    record JSONB NOT NULL,
    CHECK ((status = 'Started') = (ended_at IS NULL))
);

CREATE INDEX loom_execution_session_timeline_idx
    ON loom_execution_session (timeline_id, started_at, session_id);
