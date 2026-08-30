---
task: SCHD-T04
issue: 406
status: planned
depends_on: [405]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T04 — Add Runtime façade for Scheduler Timeline discovery

## Goal

Expose the T03 persistence capability through Runtime so application code does
not interpret `PgStorage` state directly.

## Scope

- Add one operational/read-only Runtime method delegating the T03 bound/cursor.
- Pass targets and continuation through without a second discovery policy.
- Preserve construction paths that do not call discovery.
- Keep discovery free of claims, commits, World-Time changes, Sessions and
  handler/lease/retry filtering.

## Acceptance

- [ ] `loom-server` can discover through Runtime rather than raw Storage.
- [ ] Runtime remains the authority for `drive_timeline` and all later
      semantic decisions.
- [ ] Controlled-store tests prove exact argument/result pass-through,
      typed persistence errors and no mutation.
- [ ] No public API/Boundary/Client surface is added.
