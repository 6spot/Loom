---
task: SCHD-T08
issue: 410
status: planned
depends_on: [406, 407, 409]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T08 — Prove InMemory/PostgreSQL Scheduler discovery contract parity

## Goal

Close Stage 2 with one Runtime-mediated behavioral matrix proving equivalent
InMemory and real PostgreSQL 18 discovery.

## Required matrix and acceptance

- [ ] No Pending, one Pending, duplicate same-Timeline Pending and
      terminal-only cases agree.
- [ ] Future-World-Time Pending Work is present on both backends.
- [ ] Multiple target identities, bound and continuation behavior are
      deterministic and equivalent.
- [ ] Repeated read is stable and discovery does not mutate Work/Timeline
      state.
- [ ] Required rows execute through Runtime on real PostgreSQL 18; no fake or
      self-skipped live evidence is counted.
- [ ] Relevant fmt/check/clippy/tests and the PostgreSQL gate pass.

Completion exposes T09 directly; Stage tracker `#400` closure is not a hard
dependency.
