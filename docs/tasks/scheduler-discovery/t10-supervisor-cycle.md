---
task: SCHD-T10
issue: 412
status: in_progress
depends_on: [411]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at:
completion_pr: 445
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

## Progress Log

- 2026-08-30 — Implemented `SchedulerSupervisor::run_cycle` using the Runtime
  discovery façade, the existing scheduler poll limit and sequential
  `Runtime::drive_timeline` calls. Added an application-owned cycle report and
  coverage for empty, bounded, exact-target, Blocked and stale-discovery Idle
  outcomes.

## Verification Evidence

- `cargo fmt --all -- --check` — passed.
- `git diff --check` — passed.
- `cargo test -p loom-server --lib -j1` — attempted; the host filesystem was
  full while Cargo wrote `hashbrown`/`sqlx-core` artifacts (`No space left on
  device`), before the crate compiled. Focused test execution remains pending
  available disk space.
