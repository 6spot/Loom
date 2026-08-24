-- M9-T3: normalized, bidirectional provenance for committed World Events.
-- The relation is written in the same authority transaction as the Event and
-- Timeline logical commit. Event identity is the immutable pair allocated by
-- Runtime before the transaction; no payload or causal edge carries Session
-- provenance.
CREATE TABLE loom_execution_session_event (
    timeline_id UUID NOT NULL,
    event_id UUID NOT NULL,
    event_seq NUMERIC(20, 0) NOT NULL
        CHECK (event_seq BETWEEN 1 AND 18446744073709551615),
    session_id UUID NOT NULL
        REFERENCES loom_execution_session(session_id) ON DELETE RESTRICT,
    PRIMARY KEY (timeline_id, event_id),
    UNIQUE (session_id, event_seq),
    FOREIGN KEY (timeline_id, event_id)
        REFERENCES loom_event(timeline_id, event_id) ON DELETE RESTRICT
);

CREATE INDEX loom_execution_session_event_session_idx
    ON loom_execution_session_event (session_id, event_seq, timeline_id, event_id);

