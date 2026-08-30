---
task: SCHD-T19
issue: 421
status: in_progress
depends_on: [417]
created_at: 2026-08-30
started_at: 2026-08-31
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T19 — Prove a Timeline forked after startup is auto-scheduled

## Goal

Prove that a child Timeline forked while the server is running is discovered
and progressed automatically, independently of World creation.

## Scope and acceptance

- [x] Use a real LoomServer and controlled PostgreSQL 18 with no fixed target
      configuration; create/open the source through supported surfaces.
- [x] Fork after startup through the formal Timeline API/client, ensure the
      child has representative Pending Work, and observe it through formal
      History/Facet/Admin reads without manual drive or ID injection.
- [x] Verify parent/child branch isolation and stable required live execution.
- [x] Do not alter fork/Work cloning semantics or substitute direct SQL,
      restart or the T18 World-create-only scenario.

## Progress Log

- 2026-08-31 — Added the real-process `loom-server` integration proof at
  `apps/loom-server/tests/t19_fork_auto_schedule.rs`. It provisions an
  isolated controlled PostgreSQL 18 database, starts `loom-server` with an
  empty inherited environment and no Scheduler target IDs, creates the source
  World after readiness, forks through `LoomClient`, and triggers a child-only
  counter reaction Work through the public Action API.

## Verification Evidence

- `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_control cargo test -p loom-server --test t19_fork_auto_schedule -- --nocapture` — PASS; real `loom-server` process, isolated child database, public Timeline/History/Facet/Admin reads, automatic child Work completion, and unchanged parent state.
- `cargo clippy -p loom-server --test t19_fork_auto_schedule -- -D warnings` — PASS.
- `cargo fmt --all -- --check` — PASS.
