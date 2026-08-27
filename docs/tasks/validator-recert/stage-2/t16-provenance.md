---
task: VALR-T16
issue: 321
status: in_progress
depends_on: [314]
created_at: 2026-08-27
---

## Scope

T16 owns public-consumer validation for CV-031..CV-033. The suite uses only
formal `loom-client` Action, History and Admin services for observations. Its
test-local InMemory/PostgreSQL composition publishes compatible R1/R2
descriptors through the Runtime persistence port and rebuilds the HTTP/
Runtime boundary while preserving the backing store. It does not edit central
registry wiring, production Runtime/Storage semantics or shared test harnesses.

## Evidence record

| CV | Public observation | Current result |
| --- | --- | --- |
| CV-031 | Seed E1 in S1, resolve E1→S1, inspect S1's R1, activate R2, reread Event history and Session, then repeat through a controlled boundary restart. | InMemory and live PostgreSQL integration paths pass. |
| CV-032 | Seed E1/S1 under R1, activate compatible R2, commit E2/S2, assert public Event history and Event→Session mappings remain stable while S2 is pinned to R2, then repeat after restart. | InMemory and live PostgreSQL integration paths pass. |
| CV-033 | Required non-secret implementation identity, ReadSet, Runtime-mediated call graph and controlled entropy evidence via Admin Session projection. | InMemory and live PostgreSQL integration paths pass with a test-local Capability composed through the approved dev-only `loom-protocol` seam. |

The production validator records CV-033 only after a committed root Action has
performed a public Facet read, Runtime-mediated child subresolution and
controlled entropy request. Assertions use only `loom-client` Action/History/
Admin projections and compare the same R1 Session/Event before and after R2
activation plus controlled boundary restart; implementation identity and
version are checked as non-secret Runtime Revision metadata.

## Verification

- `cargo fmt --all -- --check` — pass for the T16 candidate.
- `cargo check -p loom-validator --all-targets` — pass after T16 implementation.
- `cargo clippy -p loom-validator --all-targets -- -D warnings` — pass.
- `cargo test -p loom-validator --test provenance -- --nocapture --test-threads=1` — 9 passed, 0 failed, 0 ignored; CV-031/CV-032 and CV-033 passed on InMemory and live PostgreSQL, with controlled boundary restart coverage.
- Live PostgreSQL paths are composed through the repository-managed PostgreSQL 18 test service and a real `PgServer` boundary rebuild; no reconnect-only result is accepted for CV-031/CV-032.
- `python3 tools/check_architecture.py`, `python3 tools/check_storage_sql_ownership.py`, `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json`, and `git diff --check` remain required before handoff.

## Progress Log

- 2026-08-27 — Reworked the T09 scaffold on the approved direct test-only `loom-protocol` dependency. Added a test-local Capability whose root resolver performs the required public Facet read, Runtime-mediated call and controlled entropy request; CV-033 now passes through InMemory and live PostgreSQL controlled boundary restart. CV-031/CV-032 remain covered by the same durable public Event→Session→Revision checks.
