---
task: SCHD-T04
issue: 406
status: completed
depends_on: [405]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 441
merge_sha: 491df2296d18a459caabb546aacbf701bbc22376
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

- [x] `loom-server` can discover through Runtime rather than raw Storage.
- [x] Runtime remains the authority for `drive_timeline` and all later
      semantic decisions.
- [x] Controlled-store tests prove exact argument/result pass-through,
      typed persistence errors and no mutation.
- [x] No public API/Boundary/Client surface is added.

## Completion evidence

- Delivery PR #441 merged on 2026-08-30 as
  `491df2296d18a459caabb546aacbf701bbc22376`.
