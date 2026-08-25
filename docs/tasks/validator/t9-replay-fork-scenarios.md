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

## Scope

- `CV-005` reopen/replay a committed Timeline state at a supported committed version without re-running capability logic. The supported public mechanism is `ForkTimelineRequest::at_version`; direct same-Timeline historical materialization is not a public operation and is recorded as a gap.
- `CV-006` head fork creates a distinct Timeline while preserving World/binding identity semantics (`WorldId` preserved, `TimelineId` distinct, `TimelineAncestry` fork metadata, `CatalogService` binding).
- `CV-007` child branch mutation does not leak into parent/sibling visible state, observed only via `QueryService::get_facet` and `HistoryService::list_events`.
- `CV-008` historical fork/reopen preserves ancestry-visible history up to the fork `TimelineVersion` while excluding ancestor-future and sibling state where the formal API exposes those operations (`TimelineSnapshot::ancestry`, `HistoryService`).
- `CV-009` representative fork/reopen behavior remains correct after PostgreSQL restart. `InMemory` is ephemeral per-scenario and is explicitly `unavailable`; `PostgreSQL` checks `LOOM_TEST_POSTGRES_URL` and reports `skipped` when absent, `pass` via fresh `LoomClient` re-instantiation when configured.

No direct Runtime/Storage, SQLx/`PgStorage`, secondary index, or remediation authority is part of this task. Scenarios are intentionally public-consumer checks; they validate contract shapes and evidence without requiring a live server for unit determinism. Live PostgreSQL evidence remains observable via the `BackendHarness` when the repository composition root is running.

## Public/Formal Boundary

All scenario code executes via `BackendContext` containing only a `LoomClient`. The client is built from a public base URL and exercises only versioned `loom-api` request/response types (`TimelineTarget`, `TimelineVersion`, `ForkTimelineRequest`, `FacetQuery`, `EventQuery`, `TimelineSnapshot`). No `loom-runtime`, `loom-storage`, `loom-boundary`, `loom-core`, `loom-protocol`, `loom-capability`, `loom-agency`, or `loom-neutral` import exists in `apps/loom-validator`.

Unavailable public operations are factual gaps in `Finding` evidence:

- `finding:gap:same-timeline-historical-materialization-is-not-a-public-operation` (`CV-005`);
- `finding:gap:inmemory-durable-restart-is-not-a-public-capability` (`CV-009` InMemory).

## Progress Log

- 2026-08-25 — Registered `CV-005`–`CV-009` with capability area `replay-fork`, `InMemory`/`PostgreSQL` support, harness-driven execution via `loom-client` formal surfaces, explicit unavailable/prerequisite reporting, and deterministic InMemory fixtures; wired `validator_registry` and CLI dispatcher.

## Verification Evidence

- `cargo fmt --all -- --check` → pending.
- `cargo test -p loom-validator --all-features` → pending (including `scenarios::tests::in_memory_variants_run_deterministically`, `postgresql_missing_prerequisite_is_not_a_pass`, `isolation_checks_only_use_supported_query_surfaces`, `missing_public_operation_is_reported_factually`, `postgresql_variant_executes_live_when_configured`).
- `cargo check --workspace --all-targets --all-features` → pending.
- `cargo clippy -p loom-validator --all-targets --all-features -- -D warnings` → pending.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` → pending.
- `python3 tools/check_storage_sql_ownership.py` → pending (validator fence remains clean, only `loom-client` + `loom-api` contract imports).
- `cargo run -p loom-validator -- --list` → pending (should enumerate `CV-005`–`CV-009`).

Acceptance remains pending reviewer confirmation.
