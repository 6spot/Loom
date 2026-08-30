---
task: SCHD-T18
issue: 420
status: completed
depends_on: [417]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-31
completion_pr: 456
merge_sha: 3b40633b70f232d64927f75ece461dec63b56897
---

# SCHD-T18 — Prove a World created after server startup is auto-scheduled

## Goal

Prove that a World created after a real server is already running becomes
automatically Scheduler-visible without restart, configuration or manual
drive.

## Scope and acceptance

- [x] Start the real `LoomServer`/HTTP boundary against controlled PostgreSQL
      18 with normal config and no target fields.
- [x] Create a representative World through supported public/client surfaces,
      observe its Pending Scheduler obligation through formal History/Facet/
      Admin reads, and make no internal helper call.
- [x] Assert no restart/rebuild/env mutation and no semantic proof via direct
      SQL or unbounded sleeps.
- [x] The required live PG18 test actually executes and remains stable.

## Progress Log

- 2026-08-31 — Implementing the focused real `LoomServer`/HTTP/client gate:
  create a World after the target-neutral server is already serving, schedule
  a neutral reaction through the public Action API, and observe Scheduler
  progression through public Facet, History and Admin reads.
- 2026-08-31 — Post-merge completion audit: delivery PR #456 merged as
  `3b40633b70f232d64927f75ece461dec63b56897`; the live World-create evidence
  and acceptance are reconciled here.

## Verification Evidence

- `bash tools/test.sh -p loom-server --lib application::tests::world_created_after_server_start_is_auto_scheduled_over_public_http -- --exact --nocapture --test-threads=1` — PASS against the PG18 Compose service; repeated three times.
- `bash tools/test.sh -p loom-server --lib -- --test-threads=1` — 30 passed.
- `cargo check --workspace --exclude loom-validator --all-targets
  --all-features` and workspace Clippy with `-D warnings` — PASS.
- `python3 tools/check_architecture.py` and `python3 tools/check_storage_sql_ownership.py` — PASS.
- PR #456 CI run `33331396484` — Classify changes, Task ledger governance,
  Dependency and security policy and Rust checks passed; PostgreSQL and
  Compose lanes were correctly skipped for the application-test-only change.
