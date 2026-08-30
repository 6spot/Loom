---
task: SCHD-T16
issue: 418
status: completed
depends_on: [417]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-31
completion_pr: 453
merge_sha: 37f81a12116b8bcd1b697c39f927bf996a41ff0c
---

# SCHD-T16 — Remove Scheduler target variables from Compose + env template

## Goal

Make the official deployment stop exposing fixed Scheduler World/Timeline
target IDs.

## Scope and acceptance

- [x] Remove both target variables from `compose.yaml` and the optional-target
      block from `.env.example`.
- [x] Keep `LOOM_WORKER_SCHEDULER_POLL_LIMIT` and `LOOM_WORKER_POLL_MS` and
      preserve PostgreSQL health dependency, ports and `./loom` bind mounts.
- [x] Do not add a replacement config, service, bootstrap/default World or
      Scheduler volume.
- [x] Compose config/static checks prove no target IDs are rendered.

Rust and prose documentation remain outside this leaf.

## Progress Log

- 2026-08-31 — Post-merge completion audit: delivery PR #453 merged as
  `37f81a12116b8bcd1b697c39f927bf996a41ff0c`; the target-neutral Compose/env
  contract and acceptance evidence are reconciled here.

## Verification Evidence

- `docker compose -f compose.yaml config --quiet` and the rendered-config
  target-ID scan — passed; worker poll/limit settings, PostgreSQL health
  dependency, ports and `./loom` bind mounts remain present.
- PR #453 CI run `33329074241` — Compose config passed; the remaining lanes
  were correctly skipped because this delivery was deployment-only.
