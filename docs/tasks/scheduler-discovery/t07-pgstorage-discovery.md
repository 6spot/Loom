---
task: SCHD-T07
issue: 409
status: planned
depends_on: [405, 408]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T07 — Implement PgStorage Scheduler discovery adapter

## Goal

Wire the T06 SQL into `PgStorage` as the T03 persistence implementation.

## Scope and acceptance

- [ ] Load repository SQL through the existing `include_str!` ownership pattern
      and implement the T03 trait.
- [ ] Bind bound/cursor values once, decode typed target IDs with existing
      helpers, and preserve SQL order/continuation.
- [ ] Map SQL/decoding failures to the typed storage error without exposing
      SQLx/PostgreSQL types above `loom-storage`.
- [ ] Keep the operation read-only and avoid schema/index or claim changes.
- [ ] Focused success, empty-result and error-mapping tests plus standard
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
- 2026-08-30 — Reviewer D-001 governance reconciliation: T03 (#405) and T06
  (#408) remain `planned`, so T07 was reverted from `in_progress` to `planned`,
  its start marker was cleared, and acceptance was reset to pending. The hard
  dependency declarations remain unchanged; the implementation evidence above
  is retained while canonical eligibility waits for dependency completion.

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
- `python3 tools/validator_ready.py --root docs/tasks/scheduler-discovery
  --check` — passed (exit 0 with no real ledger invariant violations); T07 is
  correctly blocked by its still-planned hard dependencies.

The repository-wide `bash tools/test.sh --workspace --all-features` attempt
reached the Validator live gate but reported an unrelated existing `CV-016`
PostgreSQL idempotency-key collision; all storage-focused checks above passed.
The task remains `planned` until T03 and T06 are completed, consistent with
the task-ledger dependency-eligibility convention.
