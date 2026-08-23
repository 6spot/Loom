-- M6-T4: preserve the logical schedule high-water mark across forks.
--
-- A child stores only historically Pending Work. The high-water mark is
-- therefore Timeline state rather than a derivation from the child Work rows.

ALTER TABLE loom_timeline
    ADD COLUMN logical_schedule_order NUMERIC(20, 0) NOT NULL DEFAULT 0
        CHECK (logical_schedule_order BETWEEN 0 AND 18446744073709551615);

UPDATE loom_timeline AS timeline
SET logical_schedule_order = COALESCE(
    (
        SELECT MAX(work.logical_schedule_order)
        FROM loom_work AS work
        WHERE work.timeline_id = timeline.timeline_id
    ),
    0
);
