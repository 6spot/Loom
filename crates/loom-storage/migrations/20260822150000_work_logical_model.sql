-- M5-T1: replace lease-oriented Work columns with persistent logical state.
--
-- Existing M1-M3 rows have no recorded scheduling commit/order. The one-time
-- backfill uses the stored semantic due value (or the owning Timeline's
-- current World Time for legacy Immediate rows), then a stable legacy-row
-- ordering. This ordering is migration data only; new logical order is
-- allocated by the Runtime commit path and never derived from WorkId.

ALTER TABLE loom_work
    ADD COLUMN target_kind TEXT,
    ADD COLUMN target_owner TEXT,
    ADD COLUMN target_handler TEXT,
    ADD COLUMN target_agent_id UUID,
    ADD COLUMN target_cognition TEXT,
    ADD COLUMN effective_due_world_time BIGINT,
    ADD COLUMN logical_schedule_order NUMERIC(20, 0);

UPDATE loom_work
SET target_kind = 'capability_work',
    target_handler = handler;

UPDATE loom_work AS work
SET effective_due_world_time = COALESCE(work.due_world_time, timeline.world_time)
FROM loom_timeline AS timeline
WHERE timeline.timeline_id = work.timeline_id;

WITH legacy_order AS (
    SELECT
        work.timeline_id,
        work.work_id,
        ROW_NUMBER() OVER (
            PARTITION BY work.timeline_id
            ORDER BY
                COALESCE(work.due_world_time, timeline.world_time),
                work.causal_event_id NULLS FIRST,
                work.handler,
                work.schema_revision,
                work.payload::text,
                work.work_id
        ) AS logical_schedule_order
    FROM loom_work AS work
    JOIN loom_timeline AS timeline
      ON timeline.timeline_id = work.timeline_id
)
UPDATE loom_work AS work
SET logical_schedule_order = legacy_order.logical_schedule_order
FROM legacy_order
WHERE legacy_order.timeline_id = work.timeline_id
  AND legacy_order.work_id = work.work_id;

ALTER TABLE loom_work
    ALTER COLUMN target_kind SET NOT NULL,
    ALTER COLUMN effective_due_world_time SET NOT NULL,
    ALTER COLUMN logical_schedule_order SET NOT NULL,
    ADD CONSTRAINT loom_work_target_shape_ck CHECK (
        (
            target_kind = 'capability_work'
            AND target_handler IS NOT NULL
            AND target_agent_id IS NULL
            AND target_cognition IS NULL
        )
        OR (
            target_kind = 'agency_wake'
            AND target_handler IS NULL
            AND target_owner IS NULL
            AND target_agent_id IS NOT NULL
            AND target_cognition IS NOT NULL
            AND target_cognition <> ''
        )
    ),
    ADD CONSTRAINT loom_work_logical_order_ck
        CHECK (logical_schedule_order BETWEEN 1 AND 18446744073709551615),
    ADD CONSTRAINT loom_work_agent_fk
        FOREIGN KEY (timeline_id, target_agent_id)
        REFERENCES loom_entity(timeline_id, entity_id)
        ON DELETE RESTRICT;

ALTER TABLE loom_work
    DROP COLUMN handler,
    DROP COLUMN due_world_time;

DROP INDEX IF EXISTS loom_work_claim_idx;

CREATE INDEX IF NOT EXISTS loom_work_claim_idx
    ON loom_work (
        timeline_id,
        status,
        effective_due_world_time,
        logical_schedule_order,
        available_at
    )
    WHERE status = 'pending';
