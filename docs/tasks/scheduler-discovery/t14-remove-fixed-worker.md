---
task: SCHD-T14
issue: 416
status: planned
depends_on: [415]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T14 — Remove obsolete fixed-target SchedulerWorker path

## Goal

Remove the old application model in which one `SchedulerWorker` permanently
owns one configured `TimelineTarget`, after the Supervisor is wired.

## Scope and acceptance

- [ ] Remove the target-bound worker/constructor and helpers that only poll it.
- [ ] Rehome relevant timing/shutdown tests to Supervisor coverage and remove
      stale fixed-worker comments/docs.
- [ ] Keep `Runtime::drive_timeline` and Runtime/storage fencing tests intact;
      no dead compatibility path preserves the old model.
- [ ] No ServerConfig/env, Compose/docs or worker-pool changes are included.
- [ ] fmt/check/clippy/tests pass.
