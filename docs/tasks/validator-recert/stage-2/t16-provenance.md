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
| CV-033 | Required non-secret implementation identity, ReadSet, Runtime-mediated call graph and controlled entropy evidence via Admin Session projection. | **Needs decision:** current `loom-validator` T16-only dependency boundary cannot compose the required test-local Capability because `loom-protocol` is not a direct allowed dependency; no truthful non-empty call/entropy observation is manufactured. |

The production validator records CV-033 as `Unavailable` with the exact gap.
An empty call graph or empty entropy evidence is not treated as a pass.

## Verification

- `cargo fmt --all` — run for the T16 candidate.
- `cargo check -p loom-validator --all-targets` — pass after T16 implementation.
- `cargo test -p loom-validator --test provenance -- --nocapture --test-threads=1` — 8 passed, 0 failed, 0 ignored; CV-031/CV-032 passed on InMemory and live PostgreSQL, and CV-033 accurately asserted the recorded unavailable gap.
- Live PostgreSQL paths are composed through the repository-managed PostgreSQL 18 test service and a real `PgServer` boundary rebuild; no reconnect-only result is accepted for CV-031/CV-032.
- `python3 tools/check_architecture.py`, `python3 tools/check_storage_sql_ownership.py`, `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json`, and `git diff --check` remain required before handoff.

## Progress Log

- 2026-08-27 — Replaced the T09 scaffold with public Event→Session→Revision checks for CV-031/CV-032 and a factual CV-033 decision gap. Added dedicated InMemory/PostgreSQL revision fixtures and controlled boundary restart coverage in `tests/provenance.rs`. Final targeted rerun, fmt/check/clippy, architecture, storage ownership and ledger checks all pass; CV-033 remains a Leader decision point.
