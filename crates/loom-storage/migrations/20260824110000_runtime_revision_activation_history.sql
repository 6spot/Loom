-- Successful Runtime Revision activations are append-only Platform History.
-- The active singleton and this ledger are changed by one storage transaction.

CREATE TABLE loom_runtime_revision_activation (
    activation_generation NUMERIC(20, 0) PRIMARY KEY
        CHECK (activation_generation BETWEEN 1 AND 18446744073709551615),
    revision_id TEXT NOT NULL REFERENCES loom_runtime_revision(revision_id)
        ON DELETE RESTRICT,
    activated_at BIGINT NOT NULL
);

-- M4 stored the active selection before the append-only ledger existed. Carry
-- that already committed selection forward exactly once during migration.
INSERT INTO loom_runtime_revision_activation (
    revision_id,
    activation_generation,
    activated_at
)
SELECT revision_id,
       activation_generation,
       activated_at
FROM loom_runtime_active_revision
WHERE revision_id IS NOT NULL;
