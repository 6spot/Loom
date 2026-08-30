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

## Progress Log

- 2026-08-30 — Added the target-neutral `SchedulerSupervisor` shell under
  `apps/loom-server`. It owns one generic Runtime, application clock,
  `WorkerConfig`, shared shutdown signal and in-memory
  `SchedulerDiscoveryCursor` frontier; it does not store a fixed Timeline
  target or add polling/wiring/concurrency behavior.
- 2026-08-30 — Added InMemory construction and shared-shutdown ownership tests.
- 2026-08-30 — Delivery is in PR #444; completion metadata remains pending
  review and merge.

## Verification Evidence

- `cargo fmt --all -- --check` — passed.
- `git diff --check` — passed.
- `cargo test -p loom-server --lib -j1` — passed: 8 loom-server unit tests,
  including the two new Supervisor tests.
- `cargo clippy -p loom-server --all-targets -- -D warnings` was attempted;
  the host filesystem exhausted its remaining space while writing the
  dependency query cache, before a lint diagnostic was reported. The task
  remains pending review/merge evidence in the canonical ledger.
