---
task: SCHD-T18
issue: 420
status: planned
depends_on: [417]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T18 — Prove a World created after server startup is auto-scheduled

## Goal

Prove that a World created after a real server is already running becomes
automatically Scheduler-visible without restart, configuration or manual
drive.

## Scope and acceptance

- [ ] Start the real `LoomServer`/HTTP boundary against controlled PostgreSQL
      18 with normal config and no target fields.
- [ ] Create a representative World through supported public/client surfaces,
      observe its Pending Scheduler obligation through formal History/Facet/
      Admin reads, and make no internal helper call.
- [ ] Assert no restart/rebuild/env mutation and no semantic proof via direct
      SQL or unbounded sleeps.
- [ ] The required live PG18 test actually executes and remains stable.
