---
task: SCHD-T20
issue: 422
status: planned
depends_on: [417]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T20 — Prove restart resumes pending Scheduler obligations without target config

## Goal

Prove persisted Pending obligations are rediscovered and resumed after a real
server boundary restart without a fixed target or persisted in-memory cursor.

## Scope and acceptance

- [ ] Start a real server with controlled PostgreSQL 18 and no target fields,
      create representative Pending Work, then stop/rebuild the boundary while
      preserving PostgreSQL state.
- [ ] Restart with the same normal deployment config, do not copy a cursor or
      inject IDs, and observe recovery/progression through formal public/Admin/
      History surfaces.
- [ ] Verify existing Work lease/fence/retry semantics remain authoritative.
- [ ] Use a real application restart, not reconnect-only substitution; no new
      scheduler state, restart manager, direct SQL assertion or manual drive.
