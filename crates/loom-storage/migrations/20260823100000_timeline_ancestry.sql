-- M6-T3: immutable current-head Timeline ancestry.
--
-- A child materializes its fork-point state locally but keeps the parent
-- Timeline/version explicit. Ancestor Event rows and Sessions remain in their
-- original Timeline; the optional Event identity is therefore qualified by
-- parent_timeline_id rather than constrained to the child ledger.

ALTER TABLE loom_timeline
    ADD COLUMN parent_timeline_id UUID REFERENCES loom_timeline(timeline_id) ON DELETE RESTRICT,
    ADD COLUMN fork_parent_head_event_seq NUMERIC(20, 0)
        CHECK (fork_parent_head_event_seq IS NULL
            OR fork_parent_head_event_seq BETWEEN 0 AND 18446744073709551615),
    ADD COLUMN fork_parent_state_revision NUMERIC(20, 0)
        CHECK (fork_parent_state_revision IS NULL
            OR fork_parent_state_revision BETWEEN 0 AND 18446744073709551615),
    ADD COLUMN fork_parent_event_timeline_id UUID,
    ADD COLUMN fork_parent_event_id UUID,
    ADD CONSTRAINT loom_timeline_fork_position_ck CHECK (
        (parent_timeline_id IS NULL
            AND fork_parent_head_event_seq IS NULL
            AND fork_parent_state_revision IS NULL
            AND fork_parent_event_timeline_id IS NULL
            AND fork_parent_event_id IS NULL)
        OR (parent_timeline_id IS NOT NULL
            AND fork_parent_head_event_seq IS NOT NULL
            AND fork_parent_state_revision IS NOT NULL
            AND ((fork_parent_event_timeline_id IS NULL
                    AND fork_parent_event_id IS NULL)
                OR (fork_parent_event_timeline_id IS NOT NULL
                    AND fork_parent_event_id IS NOT NULL)))
    );

CREATE INDEX loom_timeline_parent_idx
    ON loom_timeline (parent_timeline_id);

-- Work semantic provenance may point at the source branch after a fork. The
-- Runtime fork/causality boundary owns validation of those qualified
-- references; the old same-Timeline-only foreign keys cannot represent that
-- contract and would reject an otherwise valid inherited Pending Work row.
ALTER TABLE loom_work
    DROP CONSTRAINT IF EXISTS loom_work_timeline_id_causal_event_id_fkey,
    DROP CONSTRAINT IF EXISTS loom_work_timeline_id_origin_work_id_fkey;
