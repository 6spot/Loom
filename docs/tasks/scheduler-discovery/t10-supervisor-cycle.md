---
task: SCHD-T10
issue: 412
status: planned
depends_on: [411]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T10 — Implement one bounded Scheduler discovery/drive cycle

## Goal

Implement one bounded Supervisor cycle that discovers through Runtime and
drives each discovered target once through `Runtime::drive_timeline`.

## Scope and acceptance

- [ ] Use `WorkerConfig::scheduler_poll_limit()` as both the existing bounded
      discovery/drive limit and no new discovery configuration.
- [ ] Sample platform timing as required and call `drive_timeline` once per
      discovered target.
- [ ] Treat normal Executed/Blocked/Advanced/Idle/budget outcomes as per-target
      results and do not reinterpret them as another target's chronology.
- [ ] Empty, bounded-N, exact-target and normal Blocked/Idle tests pass.
- [ ] No long-running loop, cursor fairness beyond the page, parallel spawn,
      direct claim or server composition change is included.
