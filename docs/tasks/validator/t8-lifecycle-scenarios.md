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
| CV-003 | lifecycle: dispose/restart/reconnect and reopen durable state via public API | lifecycle | loom-client, in-memory, postgresql | restart must recreate `LoomClient` and, for the deterministic InMemory mock, a new HTTP server task sharing durable state |
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

- Scenarios are implemented in `apps/loom-validator/src/lifecycle.rs` using only
  `loom-api` / `loom-client` (plus `tokio`/`serde_json`/`uuid` for the
  deterministic InMemory mock). No `loom-storage`, `loom-runtime`,
  `loom-boundary`, `loom-core`, `loom-protocol`, `loom-capability`,
  `loom-agency`, `loom-neutral`, `sqlx`, `PgStorage`, `axum`, or `reqwest`
  imports are present; the fence `tools/check_storage_sql_ownership.py`
  passes.
- `CV-001` creates a `WorldTemplateDescriptor` (`validator.lifecycle.t8` v1,
  `WorldInstant(42)`, `neutral.counter@^0.1.0`) via
  `WorldService::create_world_from_template` and reopens it via
  `TimelineService::inspect`.
- `CV-002` performs `neutral.counter.seed` (`value=1`) and
  `neutral.counter.increment` (`amount=2`) via `ActionService::invoke` and
  observes committed state via `QueryService::get_facet` and
  `HistoryService::list_events`.
- `CV-003` disposes the first `LoomClient` (and, for the mock, the first HTTP
  server task), creates a new `LoomClient` instance pointing at a new server
  task that shares the same `MockState` (simulating durable storage), and
  reopens the same `TimelineTarget` via public reads. The second client is
  constructed via `LoomClient::new(base_url)` – no hidden state is reused.
- `CV-004` checks `LOOM_TEST_POSTGRES_URL` before any network call. When the
  variable is absent or empty it returns `Skipped` with reason
  `missing LOOM_TEST_POSTGRES_URL; PostgreSQL evidence is unavailable`. When
  present but the service is unavailable it returns `Unavailable`. Only a
  successful live PostgreSQL round-trip can return `Pass`; the result is never
  synthesized as `pass` when evidence is missing. The check uses the same
  public `LoomClient` surfaces as the InMemory scenarios.
- The deterministic InMemory mock is a minimal `tokio::net::TcpListener`
  HTTP/JSON server that implements the subset of `loom-boundary` routes
  required for lifecycle (`/v1/worlds/from-template`, `/v1/actions`,
  `/v1/timelines/inspect`, `/v1/query/facet`, `/v1/history/events`) using
  `loom-api` types and an in-memory `HashMap` for Worlds/Facets/Events. It is
  not a validator-only API shortcut – it speaks the same public HTTP/JSON
  contract as `loom-boundary` and is exercised only via `LoomClient`.

No autoscaling, archiving, or broad scenario coverage is part of this leaf.

## Progress Log

- 2026-08-25 — Implemented stable lifecycle descriptors, deterministic
  InMemory mock, public-surface executors with genuine restart, PostgreSQL
  prerequisite handling, CLI integration, and contract tests under GitHub issue
  #260.

## Verification Evidence

- `cargo fmt --all -- --check` → passed.
- `cargo check -p loom-validator --all-targets --all-features` → passed.
- `cargo check --workspace --all-targets --all-features` → passed.
- `cargo clippy -p loom-validator --all-targets --all-features -- -D warnings` → passed.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` → passed.
- `cargo test -p loom-validator --all-features` → 89 tests passed (including lifecycle
  `cv001_passes_on_in_memory_mock`, `cv002_and_cv003_pass_on_in_memory_mock`,
  `cv004_is_skipped_on_in_memory_backend`, `cv004_prerequisite_is_not_reported_as_pass`,
  `lifecycle_uses_only_public_surfaces`, and existing runner/backend/reports suites).
- `cargo test --workspace --all-features` → passed for validator, Runtime, Storage, and composition suites (PostgreSQL suites skipped when `LOOM_TEST_POSTGRES_URL` absent, as intended).
- `python3 tools/check_storage_sql_ownership.py` → passed.
- `python3 tools/check_architecture.py` → passed.
- `cargo run -q -p loom-validator -- --list` → 4 scenarios (`CV-001`..`CV-004`) listed deterministically.
- `cargo run -q -p loom-validator -- --json /tmp/validator-report.json` → `3 pass, 1 skipped, result_state=prerequisite_unavailable` with `CV-001..CV-003` pass and `CV-004` skipped (`missing LOOM_TEST_POSTGRES_URL`); artifact is canonical JSON with `backend`, `counts`, `result_state`, `results`, `run`, `schema_version`.
- `LOOM_TEST_POSTGRES_URL=postgresql://... cargo run -q -p loom-validator -- --json /tmp/pg.json` → `3 pass, 1 unavailable` when no live PG service; `CV-004` is `unavailable` (never `pass`) – verifies `missing live evidence is not reported as pass`.
- `cargo run -q -p loom-validator -- CV-001` → `CV-001 pass` (single selection works).
- `cargo run -q -p loom-validator -- --group lifecycle` → `3 total` filtered deterministically.

Acceptance remains pending reviewer confirmation.
