---
task: SCHD-T09
issue: 411
status: completed
depends_on: [410]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 444
merge_sha: 5bab194f2d8ad29f2aa4fc23861e2777ab177272
---

# SCHD-T09 — Introduce target-neutral SchedulerSupervisor type

## Goal

Introduce the application-owned Supervisor shell without implementing its full
polling loop.

## Scope and acceptance

- [x] Add a target-neutral `SchedulerSupervisor` under `apps/loom-server`.
- [x] Own one Runtime, platform clock, existing `WorkerConfig`, shutdown
      signal and minimal T03 cursor state; do not store a fixed target.
- [x] Preserve the current single-thread/executor-neutral topology and avoid
      server wiring, env/config changes, worker pools or spawned per-Timeline
      tasks.
- [x] InMemory construction/no-target and shutdown ownership tests pass.

## Progress Log

- 2026-08-30 — Added the target-neutral `SchedulerSupervisor` shell under
  `apps/loom-server`. It owns one generic Runtime, application clock,
  `WorkerConfig`, shared shutdown signal and in-memory
  `SchedulerDiscoveryCursor` frontier; it does not store a fixed Timeline
  target or add polling/wiring/concurrency behavior.
- 2026-08-30 — Added InMemory construction and shared-shutdown ownership tests.
- 2026-08-30 — Delivery PR #444 merged as
  `5bab194f2d8ad29f2aa4fc23861e2777ab177272`; canonical completion metadata is
  reconciled here.

## Verification Evidence

- `cargo fmt --all -- --check` — passed.
- `git diff --check` — passed.
- `cargo test -p loom-server --lib -j1` — passed: 8 loom-server unit tests,
  including the two new Supervisor tests.
- Delivery PR #444 completed required repository CI before merge.
