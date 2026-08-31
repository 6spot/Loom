# Application testing

Application tests should verify product behavior through the same Loom surface the application uses in production.

## Test layers

Prefer these layers:

1. pure tests for application-only parsing, normalization and presentation logic;
2. client/contract tests for application calls into public Loom APIs;
3. end-to-end tests against a running `loom-server` for representative World workflows;
4. focused Capability tests only when the application introduces a Capability.

## Do not test by bypassing the public contract

Avoid using `PgStorage`, direct SQL or Runtime internals as application test fixtures when production application code is supposed to use the public API. Such tests can pass while the real integration is broken.

## Ingestion-heavy applications

For import/data-cleaning pipelines, test at least:

- deterministic normalization of the same input;
- malformed/partial source records;
- duplicate/retry handling;
- mapping from normalized records to Loom commands;
- rejection handling from Loom;
- idempotency expectations owned by the application;
- representative history/state reads after successful ingestion.

## Timeline behavior

If the product uses Timeline fork/simulation behavior, include an end-to-end case proving that the application can create/inspect the alternate path through public Loom surfaces without touching persistence internals.

## Verification scope

Application-only changes should run the application's focused tests first. Changes that introduce or modify a Capability, public API dependency, repository dependency edge or Loom architecture-sensitive behavior must also run the relevant Loom checks from `docs/development/` and current CI routing.

Do not run every Loom integration gate for a documentation/UI-only application edit unless the changed contract justifies it.
