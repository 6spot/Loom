---
task: SCHD-T05
issue: 407
status: completed
depends_on: [405]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 439
merge_sha: 08d420edfaac3585aa9e342fe2b6b3636aac2615
---

# SCHD-T05 — Implement InMemory Scheduler Timeline discovery

## Goal

Implement the T03 discovery contract for `InMemoryStore` for deterministic
Runtime/Supervisor tests.

## Scope and acceptance

- [x] Enumerate distinct targets containing at least one `Pending` Work,
      including future-World-Time Work.
- [x] Preserve deterministic ordering, continuation and positive page bounds.
- [x] Exclude terminal-only Timelines and return each target once.
- [x] Return only target identity/continuation; do not filter lease, retry,
      handler, budget or claimability state.
- [x] Empty, single, duplicate, terminal-only, future-time and multi-target
      tests pass without wall-clock sleeps.

## Completion evidence

- Delivery PR #439 merged on 2026-08-30 as
  `08d420edfaac3585aa9e342fe2b6b3636aac2615`.
