---
task: SCHD-T15
issue: 417
status: completed
depends_on: [416]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 452
merge_sha: f29e1cc0e828d3267385d6ca3e302ccbdd673e20
---

# SCHD-T15 — Remove Scheduler target IDs from ServerConfig

## Goal

Remove `LOOM_SCHEDULER_WORLD_ID` and `LOOM_SCHEDULER_TIMELINE_ID` from the
server configuration contract after automatic supervision replaces fixed
targets.

## Scope and acceptance

- [x] Remove `scheduler_target`, its env parser and both variable names from
      active config validation/tests while preserving identity helpers used
      elsewhere.
- [x] Update Debug/config tests so startup no longer distinguishes a Scheduler
      target; do not add replacement target/enable/discovery variables.
- [x] Preserve database and existing worker poll/limit/resource configuration.
- [x] Config tests, fmt/check/clippy and relevant workspace tests pass.

Compose/env and user documentation remain owned by T16/T17.

## Progress Log

- 2026-08-30 — Removed the obsolete Scheduler target from `ServerConfig`,
  retired both target environment variables and preserved the remaining
  database/worker/resource configuration contract.
- 2026-08-31 — Post-merge completion audit: delivery PR #452 merged as
  `f29e1cc0e828d3267385d6ca3e302ccbdd673e20`; completion metadata and
  acceptance evidence are now reconciled on the canonical ledger. This
  restores dependency eligibility for T16, T18, T19 and T20.

## Verification Evidence

- `cargo fmt --all -- --check` — passed.
- `cargo check --workspace --exclude loom-validator --all-targets
  --all-features` — passed.
- `cargo clippy --workspace --exclude loom-validator --all-targets
  --all-features -- -D warnings` — passed.
- `cargo test -p loom-server --all-features --all-targets` — passed.
- `cargo test --workspace --all-features --exclude loom-storage
  --exclude loom-validator` — passed.
- `cargo test -p loom-storage --all-features --lib` — passed.
- `python3 tools/check_architecture.py` — passed.
- `python3 tools/check_storage_sql_ownership.py` — passed.
- PR #452 CI run `33328454932` — Rust checks passed; the merged integration
  commit is recorded above. The ledger lane was correctly skipped because the
  delivery PR did not modify canonical task records.
