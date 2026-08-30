---
task: SCHD-T21
issue: 423
status: planned
depends_on: [418, 419, 420, 421, 422]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T21 — Run final one-command Compose/PostgreSQL Scheduler discovery gate

## Goal

Certify the completed automatic Scheduler discovery path on one exact
candidate using official Linux Docker Compose and PostgreSQL 18.

## Scope and acceptance

- [ ] Record one candidate SHA and use a clean/controlled data root.
- [ ] Prove `docker compose up -d` starts PostgreSQL and `loom-server` with no
      target IDs, then execute the T18 new-World, T19 fork and T20 real
      restart/resume scenarios.
- [ ] Confirm active docs/config contain no target-ID activation contract and
      run architecture, task-graph, SQL ownership, format/check, strict
      clippy, workspace tests, Rustdoc, dependency and real PostgreSQL 18
      checks on the same candidate.
- [ ] Reconcile T01–T21 records truthfully with PR, merge SHA, CI and live-gate
      evidence.

This gate may adjust orchestration/evidence only. It must reopen the owning
implementation leaf for semantic fixes and may not weaken a live scenario or
add a bus, worker pool, bootstrap or replacement config feature.
