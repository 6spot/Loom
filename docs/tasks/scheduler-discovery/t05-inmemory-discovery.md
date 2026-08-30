---
task: SCHD-T05
issue: 407
status: planned
depends_on: [405]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T05 — Implement InMemory Scheduler Timeline discovery

## Goal

Implement the T03 discovery contract for `InMemoryStore` for deterministic
Runtime/Supervisor tests.

## Scope and acceptance

- [ ] Enumerate distinct targets containing at least one `Pending` Work,
      including future-World-Time Work.
- [ ] Preserve deterministic ordering, continuation and positive page bounds.
- [ ] Exclude terminal-only Timelines and return each target once.
- [ ] Return only target identity/continuation; do not filter lease, retry,
      handler, budget or claimability state.
- [ ] Empty, single, duplicate, terminal-only, future-time and multi-target
      tests pass without wall-clock sleeps.
