-- ME-215: bind authority journal rows to the durable root Session/Ingress
-- proposal identity used by crash-window reconciliation.
ALTER TABLE loom_logical_journal
    ADD COLUMN provenance JSONB;

ALTER TABLE loom_logical_journal
    ADD CONSTRAINT loom_logical_journal_provenance_object_check
    CHECK (provenance IS NULL OR jsonb_typeof(provenance) = 'object');
