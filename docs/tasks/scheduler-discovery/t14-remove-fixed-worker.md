---
task: SCHD-T14
issue: 416
status: completed
depends_on: [415]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 451
merge_sha: 8939a4dd2f7996cf3c3ebfdf738444e00d9c9297
---

# SCHD-T14 — Remove obsolete fixed-target SchedulerWorker path

## Goal

Remove the old application model in which one `SchedulerWorker` permanently
owns one configured `TimelineTarget`, after the Supervisor is wired.

## Scope and acceptance

- [x] Remove the target-bound worker/constructor and helpers that only poll it.
- [x] Rehome relevant timing/shutdown tests to Supervisor coverage and remove
      stale fixed-worker comments/docs.
- [x] Keep `Runtime::drive_timeline` and Runtime/storage fencing tests intact;
      no dead compatibility path preserves the old model.
- [x] No ServerConfig/env, Compose/docs or worker-pool changes are included.
- [x] fmt/check/clippy/tests pass.

## Progress Log

- 2026-08-30 — Removed the obsolete fixed-target SchedulerWorker path while
  retaining shared timing/shutdown helpers for the target-neutral Supervisor.
- 2026-08-31 — Post-merge completion audit: delivery PR #451 merged as
  `8939a4dd2f7996cf3c3ebfdf738444e00d9c9297`; completion metadata and
  acceptance evidence are now reconciled on the canonical ledger.

## Verification Evidence

- `cargo fmt --all -- --check` — passed.
- `cargo check --workspace --exclude loom-validator --all-targets
  --all-features` — passed.
- `cargo clippy --workspace --exclude loom-validator --all-targets
  --all-features -- -D warnings` — passed.
- `cargo test --workspace --all-features --exclude loom-storage
  --exclude loom-validator -j1` — passed.
- `cargo test -p loom-storage --all-features --lib -j1` — passed.
- PR #451 CI run `33326763178` — Rust checks passed; the merged integration
  commit is recorded above. The ledger lane was correctly skipped because the
  delivery PR did not modify canonical task records.
