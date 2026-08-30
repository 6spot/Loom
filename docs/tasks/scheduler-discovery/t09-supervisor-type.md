---
task: SCHD-T09
issue: 411
status: planned
depends_on: [410]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T09 — Introduce target-neutral SchedulerSupervisor type

## Goal

Introduce the application-owned Supervisor shell without implementing its full
polling loop.

## Scope and acceptance

- [ ] Add a target-neutral `SchedulerSupervisor` under `apps/loom-server`.
- [ ] Own one Runtime, platform clock, existing `WorkerConfig`, shutdown
      signal and minimal T03 cursor state; do not store a fixed target.
- [ ] Preserve the current single-thread/executor-neutral topology and avoid
      server wiring, env/config changes, worker pools or spawned per-Timeline
      tasks.
- [ ] InMemory construction/no-target and shutdown ownership tests pass.
