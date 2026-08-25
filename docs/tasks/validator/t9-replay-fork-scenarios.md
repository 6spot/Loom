---
task: VAL-T9
issue: 261
status: in_progress
depends_on: [255, 256, 257, 259]
created_at: 2026-08-24
started_at: 2026-08-25
completed_at:
completion_pr:
merge_sha:
---

# VAL-T9 — Replay/fork/branch-isolation capability scenarios

Exercise Loom replay/fork behavior from the same public/formal consumer boundary used by an upper-layer application. Scenarios use only `loom-client` over the versioned `loom-api` HTTP boundary and do not import Runtime, Storage, or other implementation-only authority.

## Acceptance

- [ ] stable scenario IDs `CV-005`–`CV-009` are registered and deterministically enumerated;
- [ ] supported InMemory variants run deterministically without wall-clock or global state;
- [ ] supported PostgreSQL variants execute live when `LOOM_TEST_POSTGRES_URL` is configured and report explicit prerequisite/unavailable when absent, never `pass`;
- [ ] isolation checks observe behavior only through supported query/API surfaces (`TimelineService::inspect_timeline`, `TimelineService::fork`, `QueryService::get_facet`, `HistoryService::list_events`, `CatalogService`, `TimelineSnapshot::ancestry`);
- [ ] missing public operation is reported factually (e.g. same-Timeline historical materialization, InMemory durable restart) without a hidden validator shortcut;
- [ ] findings use the VAL feedback path without automatic remediation.

## Evidence Classification

- `MockApi` (in-process `loom_api::LoomApi` implementation under `BackendHarness` for `InMemory`) is **Validator unit evidence only**. It exercises scenario orchestration and error mapping deterministically but never counts as Loom acceptance evidence.
- **Loom acceptance evidence** for VAL-T9 is the separate real-service layer at `apps/loom-validator/tests/replay_fork.rs` (and the equivalent PostgreSQL restart coverage). It composes the real Loom service via the VAL-T8 HTTP composition (`loom-runtime` + `loom-storage` + `loom-neutral` + `loom-boundary`), connects through the versioned HTTP boundary with the production `LoomClient`, and passes a `BackendContext` with the production `LoomClient`-backed `LoomApi` to `execute_replay_fork` for `CV-005`..`CV-009`.
- VAL-T9 is **not complete from `MockApi`/unit results alone**. At least the PostgreSQL-backed real-service evidence for `CV-005`..`CV-009` (including deterministic `CV-009` restart/reconnect) must be present; `cargo test -p loom-validator` unit results without `LOOM_TEST_POSTGRES_URL` and `bash tools/test.sh` real-service results are distinct signals.

## Scope

- `CV-005` reopen/replay a committed Timeline state at a supported committed version without re-running capability logic. The supported public mechanism is `ForkTimelineRequest::at_version`; direct same-Timeline historical materialization is not a public operation and is recorded as a gap.
- `CV-006` head fork creates a distinct Timeline while preserving World/binding identity semantics (`WorldId` preserved, `TimelineId` distinct, `TimelineAncestry` fork metadata, `CatalogService` binding).
- `CV-007` child branch mutation does not leak into parent/sibling visible state, observed only via `QueryService::get_facet` and `HistoryService::list_events`.
- `CV-008` historical fork/reopen preserves ancestry-visible history up to the fork `TimelineVersion` while excluding ancestor-future and sibling state where the formal API exposes those operations (`TimelineSnapshot::ancestry`, `HistoryService`).
- `CV-009` representative fork/reopen behavior remains correct after **PostgreSQL restart**. `InMemory` is ephemeral per-scenario and is explicitly `unavailable` with `finding:gap:inmemory-durable-restart-is-not-a-public-capability`; `PostgreSQL` checks `LOOM_TEST_POSTGRES_URL` (reports `skipped`/`prerequisite` when absent, `unavailable` when the live endpoint is not reachable, never `pass`) and, when configured, performs a genuine service-boundary restart via `BackendContext::restart()` — the test harness `PgServer::restart()` terminates the current `axum` boundary task, rebuilds `Runtime`/`Boundary` against the preserved `PgStorage` database, and returns a new `LoomClient`; the scenario then verifies via public surfaces that `ancestry`/`HistoryService`/`QueryService` replay/fork state and `parent`/`child`/`sibling` isolation survive the restart, that a post-restart child mutation does not leak, and that a historical `fork at version` after restart still materializes the correct committed state.

No direct Runtime/Storage, SQLx/`PgStorage`, secondary index, or remediation authority is part of this task. Scenarios are intentionally public-consumer checks; they validate contract shapes and evidence without requiring a live server for unit determinism. Live PostgreSQL evidence remains observable via the real-service harness (`apps/loom-validator/tests/replay_fork.rs` + `tests/common::{InMemoryServer,PgServer}`) when the repository composition root or `bash tools/test.sh` PostgreSQL composition is running.

## Public/Formal Boundary

Production scenario code executes via `BackendContext` containing only a `LoomClient`. The client is built from a public base URL and exercises only versioned `loom-api` request/response types (`TimelineTarget`, `TimelineVersion`, `ForkTimelineRequest`, `FacetQuery`, `EventQuery`, `TimelineSnapshot`). Production `apps/loom-validator/src` has no `loom-runtime`, `loom-storage`, `loom-boundary`, `loom-core`, `loom-protocol`, `loom-capability`, `loom-agency`, or `loom-neutral` import; test-only acceptance composition is kept under `apps/loom-validator/tests`.

## Real Loom acceptance harness

The Validator-owned `MockApi` remains unit-test infrastructure for exercising
scenario orchestration. It is **not acceptance evidence** and its results are
classified as Validator unit evidence. The separate
`apps/loom-validator/tests/replay_fork.rs` integration test composes the real
InMemory or PostgreSQL Loom service using the VAL-T8 pattern
(`tests/common::{InMemoryServer,PgServer}` — `leaked_runtime` + `loom-boundary`
HTTP composition), connects through its HTTP boundary with the production
`LoomClient`, and passes that production client-backed `BackendContext` to
`execute_replay_fork` for `CV-005`..`CV-008`. A dedicated `CV-009` test in the
same file composes a real PostgreSQL service, injects a genuine restart
strategy (`BackendContext::with_restart_strategy(server.restart)`), and
exercises `execute_replay_fork(CV-009)` which internally calls
`BackendContext::restart()` to rebuild the boundary and reconnect through a new
public client. All assertions in this layer observe Loom state only through the
supported public client/API surfaces (`WorldService`, `ActionService`,
`TimelineService::fork`/`inspect_timeline`, `QueryService::get_facet`,
`HistoryService::list_events`, `CatalogService`, `TimelineSnapshot::ancestry`);
no `loom_storage`, `PgStorage`, or `SQLx` internals are asserted. The
PostgreSQL tests run when `LOOM_TEST_POSTGRES_URL` is configured and explicitly
report `skipped`/`prerequisite` or `unavailable` when that prerequisite/live
endpoint is absent — never `pass`.

Unavailable public operations are factual gaps in `Finding` evidence and do not
become synthetic passes:

- `finding:gap:same-timeline-historical-materialization-is-not-a-public-operation` (`CV-005` — direct same-Timeline historical materialization is not a public operation; replay is via `ForkTimelineRequest::at_version`);
- `finding:gap:inmemory-durable-restart-is-not-a-public-capability` (`CV-009` `InMemory` — `PostgreSQL` restart requires a durable store; `InMemory` is per-scenario ephemeral and explicitly returns `unavailable`, verified by `cv009_is_unavailable_on_real_in_memory_service` even against a real `InMemoryServer`).

The documented VAL-T9 completion rule cannot be satisfied solely by `MockApi`
results: the report `counts{pass:4 unavailable:1}` from unit runs documents the
gap, but the acceptance gate requires the additional real-service evidence from
`bash tools/test.sh -p loom-validator --test replay_fork` (`4` real-service
tests including `CV-009` PostgreSQL restart) and the `PostgreSQL 18 persistence
contract` CI job.

## Progress Log

- 2026-08-25 — Registered `CV-005`–`CV-009` with capability area `replay-fork`, `InMemory`/`PostgreSQL` support, harness-driven execution via `loom-client` formal surfaces, explicit unavailable/prerequisite reporting, and deterministic InMemory fixtures; wired `validator_registry` and CLI dispatcher.
- 2026-08-25 — Rework D-001/D-002: `InMemory` now uses an in-process `MockApi` that implements the public `LoomApi` contract (no `loom-runtime`/`loom-storage` import in validator) and is exercised via `BackendHarness`/`BackendContext` over the same `LoomApi` surface; `CV-005`–`CV-008` now call `WorldService::create_world_from_template`, `ActionService::invoke`, `TimelineService::fork`/`inspect_timeline`, `QueryService::get_facet`, `HistoryService::list_events` and verify replay/isolation from returned `TimelineSnapshot`/`FacetSnapshot`/`EventPage`; `PostgreSQL` now verifies live `catalog` reachability and `CV-009` performs a fresh `LoomClient` reconnect followed by `inspect`/`history` checks, returning `unavailable` when the endpoint is not reachable.
- 2026-08-25 — Added the separate real-service acceptance layer at `apps/loom-validator/tests/replay_fork.rs`. It runs `CV-005`..`CV-008` through the VAL-T8 HTTP composition and production `LoomClient`-backed `BackendContext`; the `MockApi` tests remain unit coverage only.
- 2026-08-25 — ME-272: PostgreSQL `CV-009` restart/reconnect durability via genuine boundary rebuild. `cv009` now uses `BackendContext::restart()` (harness `PgServer::restart()` preserves `PgStorage` and rebuilds `Runtime`/`Boundary`) and, through a new public client, verifies replay/fork `ancestry`/`history`, `parent 5`/`child 15`/`sibling 5` isolation, post-restart child `15→16` non-leak with `child events 3`, and historical `fork at version` (`facet 5`, `events 1`); `InMemory` remains an explicit `unavailable` gap (`finding:gap:inmemory-durable-restart-is-not-a-public-capability`) validated even against a real `InMemoryServer`.

## Verification Evidence

- `cargo fmt --all -- --check` → passed.
- `cargo test -p loom-validator --all-features` → 95 passed (including `scenarios::tests::in_memory_variants_run_deterministically` which now exercises the `MockApi` via `BackendHarness` and verifies `CV-005` replay `child facet=1 parent facet=2`, `CV-007` isolation `parent 5 child 15`, `CV-008` historical `child events 2 parent 3`, and `CV-009` `InMemory` `unavailable` gap).
- `cargo check --workspace --all-targets --all-features` → passed.
- `cargo clippy -p loom-validator --all-targets --all-features -- -D warnings` → passed (with `clippy::all` allowances for mock/scenario harness).
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` → passed.
- `python3 tools/check_storage_sql_ownership.py` → passed (validator imports only `loom-api`/`loom-client` plus `tokio`/`hyper`/`uuid` for the mock; no `loom-runtime`/`loom-storage`/`loom-core` etc.).
- `python3 tools/check_architecture.py` → passed.
- `cargo run -q -p loom-validator -- --list` → `available scenarios (5): CV-005..009` (`replay-fork`).
- `cargo run -q -p loom-validator --` → `CV-005 pass` (`replay via fork at version 1 verified: child facet=1 parent facet=2`), `CV-006 pass` (`WorldId preserved=true distinct=true`), `CV-007 pass` (`parent facet 5 child 15`), `CV-008 pass` (`child events 2 parent 3`), `CV-009 unavailable` (`inmemory-durable-restart`); `4 pass 1 unavailable`. The `MockApi` result documents the gap but is explicitly unit evidence, not Loom acceptance.
- `cargo run -q -p loom-validator -- --json /tmp/report.json` → `report.json` `backend: in-memory` `counts{pass:4 unavailable:1}` and `findings[0].evidence` contains `public-surface:loom-client::TimelineService::fork` and `gap` (`finding:gap:inmemory-durable-restart-is-not-a-public-capability`); the report alone does not satisfy the VAL-T9 completion rule.
- `BackendHarness::connect(PostgreSQL, http://127.0.0.1:1)` with `LOOM_TEST_POSTGRES_URL=postgres://localhost:5432/loom_test` → `Unavailable` (live endpoint not reachable, not `pass`); without `LOOM_TEST_POSTGRES_URL` → `Prerequisite` (`missing ...`).
- `bash tools/test.sh -p loom-validator --test replay_fork -- --nocapture` → 4 passed; the repository script started/reused `compose.test-db.yaml`, supplied the standard PostgreSQL test endpoint, and verified: `CV-005`..`CV-008` pass on real `InMemory`; `CV-005`..`CV-008` pass on live PostgreSQL when configured; `CV-009` is `unavailable` on real `InMemory` with `gap`; `CV-009` PostgreSQL restart survives a genuine `PgServer::restart()` boundary rebuild and reconnect via new `LoomClient`, verifying `ancestry`/`history`/`facet` and `parent 5`/`child 15→16`/`sibling 5` isolation via only `inspect_timeline`/`list_events`/`get_facet`.
- `bash tools/test.sh -p loom-validator --all-features` → 95 unit + 3 `lifecycle` + 4 `replay_fork` all passed.

VAL-T9 cannot be marked completed solely from `MockApi` results; the real-service evidence above (in particular `CV-009` PostgreSQL restart and the `PostgreSQL 18 persistence contract` CI job) is required for acceptance.

Acceptance remains pending reviewer confirmation.
