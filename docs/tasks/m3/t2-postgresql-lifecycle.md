---
task: M3-T2
issue: 49
status: in_progress
depends_on: [48]
created_at: 2026-08-21
started_at: 2026-08-21
completed_at:
completion_pr: 54
merge_sha:
---

# M3-T2 — PostgreSQL Lifecycle Persistence

## Goal

Harden and prove the Runtime-owned World lifecycle persistence port on PostgreSQL 18 with atomic World + initial Timeline creation and isolated integration coverage.

## Acceptance checklist

- [x] `PgStorage` implements the lifecycle port without leaking SQLx into Runtime/API;
- [x] World and initial Timeline are inserted in one transaction;
- [x] initial version/time values exactly match the Runtime request;
- [x] duplicate/conflicting identity creation rolls back completely;
- [x] existing `WorldStore::snapshot` and public Timeline inspection see the new Timeline after commit;
- [x] isolated PostgreSQL integration tests cover success and rollback semantics;
- [x] CI explicitly executes the lifecycle suite alongside existing PostgreSQL contracts.

## Verification

- [x] `python3 tools/check_architecture.py`;
- [x] `cargo fmt --all -- --check`;
- [x] `cargo check --workspace --all-targets --all-features`;
- [x] `cargo clippy --workspace --all-targets --all-features -- -D warnings`;
- [x] `cargo test --workspace --all-features`;
- [x] `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps`;
- [x] `cargo test -p loom-storage --test postgres_lifecycle -- --nocapture` on PostgreSQL 18.

## Completion evidence

- PR: #54
- merge SHA: pending implementation merge
- clean candidate SHA: `82003c734345e8bb8a01daa56409528acb6be7d9`
- CI runs: `32490492509` exposed a formatting-only failure and was superseded; clean standard CI `32490627476` passed Ubuntu/macOS plus the PostgreSQL 18 persistence contract including the new World lifecycle gate.
- notes: `postgres_lifecycle::postgres_18_world_lifecycle_is_atomic_and_immediately_readable` proves scratch migrations, exact zero initial version, exact requested World Time, `WorldStore` readability and public `TimelineService` readability. `postgres_18_world_lifecycle_conflicts_roll_back_without_partial_rows` proves typed duplicate-World and duplicate-Timeline conflicts, no orphan Timeline/World rows, reuse of a rolled-back World ID, and preservation of the original Timeline. The audited T1 `PgStorage` implementation required no semantic correction.

## Progress log

- 2026-08-21 — Task record created; waits on M3-T1 #48.
- 2026-08-21 — Started from T1 completion/audit main `02527ee48a7a08cc4c508c19512fa38155746ea5`. T1 already introduced the minimal `PgStorage` lifecycle implementation; T2 audits transaction/error classification and adds dedicated PostgreSQL 18 lifecycle success/conflict/rollback/readability evidence plus an explicit CI gate.
- 2026-08-21 — Added isolated `postgres_lifecycle` integration coverage and an explicit `PostgreSQL World lifecycle contract` step to the long-lived read-only CI workflow. First standard run `32490492509` failed only `cargo fmt --check`; runner-provided rustfmt changes were applied without semantic changes.
- 2026-08-21 — Clean candidate `82003c734345e8bb8a01daa56409528acb6be7d9` passed standard CI `32490627476`: Ubuntu/macOS architecture, format, check, clippy, workspace tests and rustdoc green; PostgreSQL 18 schema, lifecycle, public vertical, read, commit/CAS, Durable Work and stale-fence suites all green. Awaiting final task-record CI, merge and post-merge audit metadata.
