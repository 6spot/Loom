-- Execution Session outcomes are Platform History. No World Event or
-- Timeline mutation is created by adding these audit distinctions.

ALTER TABLE loom_execution_session
    DROP CONSTRAINT loom_execution_session_status_check;

ALTER TABLE loom_execution_session
    ADD CONSTRAINT loom_execution_session_status_check
    CHECK (status IN ('Started', 'Committed', 'NoChange', 'Rejected', 'Failed', 'Blocked'));
