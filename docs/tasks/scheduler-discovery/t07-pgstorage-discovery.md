---
task: SCHD-T07
issue: 409
status: in_progress
depends_on: [405, 408]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T07 — Implement PgStorage Scheduler discovery adapter

## Goal

Wire the T06 SQL into `PgStorage` as the T03 persistence implementation.

## Scope and acceptance

- [x] Load repository SQL through the existing `include_str!` ownership pattern
      and implement the T03 trait.
- [x] Bind bound/cursor values once, decode typed target IDs with existing
      helpers, and preserve SQL order/continuation.
- [x] Map SQL/decoding failures to the typed storage error without exposing
      SQLx/PostgreSQL types above `loom-storage`.
- [x] Keep the operation read-only and avoid schema/index or claim changes.
- [x] Focused success, empty-result and error-mapping tests plus standard
      storage checks pass.

## Progress Log

- 2026-08-30 — Implemented the PostgreSQL Scheduler discovery adapter using
  the repository-owned T06 SQL. The adapter validates the T03 request,
  binds the cursor components and one extra-row page bound once, decodes only
  typed World/Timeline identities, and maps SQL/decoding failures to
  `SchedulerDiscoveryError`.
- 2026-08-30 — Added focused PostgreSQL 18 coverage for ordered continuation,
  duplicate-target collapse, future/leased Pending Work visibility, empty
  results, read-only state preservation, bound validation and storage failure
  mapping.

## Verification Evidence

Verification completed on 2026-08-30:

- `git diff --check` — passed.
- `python3 tools/check_storage_sql_ownership.py` — passed.
- `cargo fmt --all -- --check` — passed.
- `cargo check --workspace --all-targets --all-features` — passed.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` —
  passed.
- `bash tools/test.sh -p loom-storage --test postgres_scheduler_discovery --
  --nocapture` — passed (3 focused PostgreSQL 18 tests).
- `cargo test -p loom-storage --all-targets --all-features` — passed (all
  storage unit/integration targets).
- `cargo test -p loom-storage --lib --all-features` — passed after cleaning
  disposable build artifacts.

The repository-wide `bash tools/test.sh --workspace --all-features` attempt
reached the Validator live gate but reported an unrelated existing `CV-016`
PostgreSQL idempotency-key collision; all storage-focused checks above passed.
The task remains `in_progress` until the delivery PR is merged, consistent
with the task-ledger convention.
