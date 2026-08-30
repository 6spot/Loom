---
task: SCHD-T15
issue: 417
status: planned
depends_on: [416]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T15 — Remove Scheduler target IDs from ServerConfig

## Goal

Remove `LOOM_SCHEDULER_WORLD_ID` and `LOOM_SCHEDULER_TIMELINE_ID` from the
server configuration contract after automatic supervision replaces fixed
targets.

## Scope and acceptance

- [ ] Remove `scheduler_target`, its env parser and both variable names from
      active config validation/tests while preserving identity helpers used
      elsewhere.
- [ ] Update Debug/config tests so startup no longer distinguishes a Scheduler
      target; do not add replacement target/enable/discovery variables.
- [ ] Preserve database and existing worker poll/limit/resource configuration.
- [ ] Config tests, fmt/check/clippy and relevant workspace tests pass.

Compose/env and user documentation remain owned by T16/T17.
