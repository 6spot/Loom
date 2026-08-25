---
task: VAL-T8
issue: 260
status: completed
depends_on: [255, 256, 257, 259]
created_at: 2026-08-24
started_at: 2026-08-25
completed_at: 2026-08-25
completion_pr:
merge_sha:
---

# VAL-T8 — Baseline lifecycle/create/reopen/restart capability scenarios

Add the first real capability scenarios that verify Loom from a supported
upper-layer/public consumer perspective across process lifecycle boundaries.

## Goal

Prove the validator on real Loom capability paths through the public
`loom-client` / `loom-api` surfaces, without introducing a validator-only
shortcut. Record unavailable capability/prerequisite factually and ensure
restart genuinely recreates the application boundary.

## Scenarios

| ID | Name | Capability area | Supported backends | Prerequisite |
| --- | --- | --- | --- | --- |
| CV-001 | lifecycle: create/open World/Timeline via public API | lifecycle | loom-client, in-memory, postgresql | none; uses `WorldService::create_world_from_template` and `TimelineService::inspect` |
| CV-002 | lifecycle: mutate via Action and observe committed state via public reads | lifecycle | loom-client, in-memory, postgresql | requires `neutral.counter` capability (installed by composition root) |
| CV-003 | lifecycle: dispose/restart/reconnect and reopen durable state via public API | lifecycle | loom-client, in-memory, postgresql | restart must terminate and rebuild the real application/service boundary (new `LoomClient` to the rebuilt boundary), never reuse shared in-process state |
| CV-004 | lifecycle: verify public observable state/provenance survives restart on PostgreSQL | lifecycle | loom-client, in-memory, postgresql | requires `LOOM_TEST_POSTGRES_URL` and a live PostgreSQL-backed Loom service; missing evidence is never `pass` |

Stable IDs are independent of Rust function/file names. Registry enumeration is
deterministic (sorted by `CV-` ID).

## Acceptance

- [x] stable scenario IDs are registered and documented;
- [x] InMemory-supported lifecycle scenarios pass deterministically;
- [x] live PostgreSQL variants run when configured and missing live evidence is not reported as pass;
- [x] scenarios use public/formal surfaces only;
- [x] representative restart genuinely recreates/reconnects the application boundary rather than reusing hidden in-process state;
- [x] findings can be written through the VAL feedback path without task-state mutation.

## Scope

- Production validator depends only on `loom-api` / `loom-client` (plus
  `serde`/`serde_json`/`tokio`/`uuid`). No `loom-storage`, `loom-runtime`,
  `loom-boundary`, `loom-neutral`, `sqlx`, `PgStorage`, `axum`, or `reqwest`
  imports appear in `apps/loom-validator/src/`; the fences
  `tools/check_storage_sql_ownership.py` and `tools/check_architecture.py`
  pass. Real InMemory/PostgreSQL service composition is test-only
  (`apps/loom-validator/tests/common/mod.rs`, dev-dependencies), the same
  pattern `loom-client` uses to exercise its boundary.
- Scenarios are implemented in `apps/loom-validator/src/lifecycle.rs` using only
  public `loom-api` trait surfaces through `loom-client::LoomClient`
  (`WorldService`, `ActionService`, `TimelineService`, `QueryService`,
  `HistoryService`). No validator-only shortcut is used.
- `CV-001` creates a `WorldTemplateDescriptor` (`validator.lifecycle.t8` v1,
  `WorldInstant(42)`, `neutral.counter@^0.1.0`) via
  `WorldService::create_world_from_template` and reopens it via
  `TimelineService::inspect`.
- `CV-002` performs `neutral.counter.seed` (`value=1`) and
  `neutral.counter.increment` (`amount=2`) via `ActionService::invoke` and
  observes committed state via `QueryService::get_facet` and
  `HistoryService::list_events`.
- `CV-003` terminates and rebuilds the real application/service boundary via the
  context restart strategy, then reconnects with a new `LoomClient` and reopens
  the same `TimelineTarget` through public reads. Production reconnects to the
  configured endpoint; the test harness injects a strategy that aborts the
  server task and rebuilds `Runtime` + HTTP boundary on the preserved store, so
  no shared in-process state is reused and no direct storage access bypasses
  the public API.
- `CV-004` checks `LOOM_TEST_POSTGRES_URL` before any network call. When the
  variable is absent or empty it returns `Skipped` with reason
  `missing LOOM_TEST_POSTGRES_URL; PostgreSQL evidence is unavailable`. When
  present but the service is unavailable it returns `Unavailable`. Only a
  successful live PostgreSQL round-trip across a real boundary rebuild can
  return `Pass`; the result is never synthesized as `pass` when evidence is
  missing. The check uses the same public `LoomClient` surfaces as the other
  scenarios.
- Real InMemory and PostgreSQL services are composed in
  `apps/loom-validator/tests/common/mod.rs` (`loom-runtime` + `loom-storage` +
  `loom-neutral` registry + `loom-boundary::router`, the same backend
  `loom-server` composes) and are served over HTTP. `tests/lifecycle.rs` runs
  the production scenario logic against them, including genuine boundary
  rebuild on restart. The negative endpoint
  `LOOM_VALIDATOR_BASE_URL=http://127.0.0.1:1` is `Unavailable`, never `pass`.

No autoscaling, archiving, or broad scenario coverage is part of this leaf.

## Progress Log

- 2026-08-25 — Implemented stable lifecycle descriptors, public-surface
  executors with genuine application-boundary restart, PostgreSQL live path, and
  contract tests under GitHub issue #260.
- 2026-08-25 — Rework per D-001/D-002/D-003 (reviewer `01a036d7-96cb-7f0b-a1c2-301580257a2f`):
  removed the validator self-built mock; scenarios now execute against real
  InMemory and PostgreSQL Loom service boundaries via the public `LoomClient`,
  restart terminates and rebuilds the real application boundary, and CI runs the
  validator lifecycle live path on PostgreSQL 18.

## Verification Evidence

- `cargo fmt --all -- --check` → passed.
- `cargo check --workspace --all-targets --all-features` → passed.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` → passed.
- `bash tools/test.sh --workspace --all-features` (live PostgreSQL 18 via
  `compose.test-db.yaml`) → passed, including loom-validator lib suite and
  `tests/lifecycle.rs`.
- `cargo test -p loom-validator --all-features` → 88 lib tests passed; 3
  integration tests passed (`tests/lifecycle.rs`).
- `LOOM_TEST_POSTGRES_URL=postgresql://... cargo test -p loom-validator --test lifecycle`
  → CV-001..CV-004 all pass against a real PostgreSQL-backed Loom service,
  including restart/provenance.
- Real `loom-server` process on PostgreSQL 18 + validator CLI:
  `LOOM_VALIDATOR_BASE_URL=http://127.0.0.1:18081 LOOM_TEST_POSTGRES_URL=postgresql://...`
  `cargo run -q -p loom-validator -- --group lifecycle` → `4 pass, 0 fail, 0
  skipped, 0 unavailable`.
- Negative endpoint: `LOOM_VALIDATOR_BASE_URL=http://127.0.0.1:1 cargo run -q -p loom-validator -- --group lifecycle`
  → `0 pass, 0 fail, 4 unavailable` (never a synthetic pass).
- `python3 tools/check_storage_sql_ownership.py` → passed.
- `python3 tools/check_architecture.py` → passed.
- `cargo run -q -p loom-validator -- --list` → 4 scenarios (`CV-001`..`CV-004`)
  listed deterministically.
- CI `.github/workflows/ci.yml` `postgres-contract` job now runs
  `cargo test -p loom-validator --test lifecycle` against PostgreSQL 18 for the
  live lifecycle path evidence.

Acceptance remains pending reviewer confirmation.
