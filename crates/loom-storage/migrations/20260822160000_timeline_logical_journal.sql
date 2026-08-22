-- M5-T2: persist Runtime-owned Timeline Logical Commit history.
--
-- The journal is semantic Timeline history, not a World Event ledger and not
-- a copy of Work lease/retry metadata. The logical revision after each commit
-- is the deterministic ordering key and is protected by the Timeline CAS.

ALTER TABLE loom_timeline
    ADD COLUMN chronology_budget_world_time BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN chronology_budget_consumed NUMERIC(20, 0) NOT NULL DEFAULT 0
        CHECK (chronology_budget_consumed BETWEEN 0 AND 18446744073709551615);

UPDATE loom_timeline
SET chronology_budget_world_time = world_time;

CREATE TABLE loom_logical_journal (
    timeline_id UUID NOT NULL REFERENCES loom_timeline(timeline_id) ON DELETE CASCADE,
    after_state_revision NUMERIC(20, 0) NOT NULL
        CHECK (after_state_revision BETWEEN 1 AND 18446744073709551615),
    before_head_event_seq NUMERIC(20, 0) NOT NULL
        CHECK (before_head_event_seq BETWEEN 0 AND 18446744073709551615),
    before_state_revision NUMERIC(20, 0) NOT NULL
        CHECK (before_state_revision BETWEEN 0 AND 18446744073709551615),
    after_head_event_seq NUMERIC(20, 0) NOT NULL
        CHECK (after_head_event_seq BETWEEN 0 AND 18446744073709551615),
    world_time_before BIGINT,
    world_time_after BIGINT,
    event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    work_transitions JSONB NOT NULL DEFAULT '[]'::jsonb,
    chronology_budget_world_time BIGINT,
    chronology_budget_before NUMERIC(20, 0)
        CHECK (chronology_budget_before IS NULL OR chronology_budget_before BETWEEN 0 AND 18446744073709551615),
    chronology_budget_after NUMERIC(20, 0)
        CHECK (chronology_budget_after IS NULL OR chronology_budget_after BETWEEN 0 AND 18446744073709551615),
    PRIMARY KEY (timeline_id, after_state_revision),
    CHECK ((world_time_before IS NULL) = (world_time_after IS NULL)),
    CHECK ((chronology_budget_world_time IS NULL)
        = (chronology_budget_before IS NULL AND chronology_budget_after IS NULL)),
    CHECK (jsonb_typeof(event_ids) = 'array'),
    CHECK (jsonb_typeof(work_transitions) = 'array')
);

CREATE INDEX loom_logical_journal_order_idx
    ON loom_logical_journal (timeline_id, after_state_revision);
