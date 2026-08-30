---
task: SCHD-T16
issue: 418
status: planned
depends_on: [417]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T16 — Remove Scheduler target variables from Compose + env template

## Goal

Make the official deployment stop exposing fixed Scheduler World/Timeline
target IDs.

## Scope and acceptance

- [ ] Remove both target variables from `compose.yaml` and the optional-target
      block from `.env.example`.
- [ ] Keep `LOOM_WORKER_SCHEDULER_POLL_LIMIT` and `LOOM_WORKER_POLL_MS` and
      preserve PostgreSQL health dependency, ports and `./loom` bind mounts.
- [ ] Do not add a replacement config, service, bootstrap/default World or
      Scheduler volume.
- [ ] Compose config/static checks prove no target IDs are rendered.

Rust and prose documentation remain outside this leaf.
