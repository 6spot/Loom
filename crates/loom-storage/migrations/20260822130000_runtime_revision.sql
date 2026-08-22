-- Runtime Revision publication and active-selection metadata are Platform
-- History. They intentionally have no foreign key to World/Timeline/Event or
-- materialized State tables, and activation never updates those authorities.

CREATE TABLE loom_runtime_revision (
    revision_id TEXT PRIMARY KEY,
    descriptor JSONB NOT NULL
);

-- A permanent singleton row makes first activation a lockable CAS operation:
-- concurrent initial activations serialize on this row instead of racing on a
-- missing-row INSERT. NULL means no revision has been explicitly activated.
CREATE TABLE loom_runtime_active_revision (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    revision_id TEXT REFERENCES loom_runtime_revision(revision_id) ON DELETE RESTRICT,
    activation_generation NUMERIC(20, 0) NOT NULL DEFAULT 0
        CHECK (activation_generation BETWEEN 0 AND 18446744073709551615),
    activated_at BIGINT,
    CHECK ((revision_id IS NULL) = (activated_at IS NULL))
);

INSERT INTO loom_runtime_active_revision (singleton)
VALUES (TRUE);
