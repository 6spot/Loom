---
task: C1-T10
issue: 499
status: planned
depends_on: [C1-T3, C1-T4, C1-T9]
created_at: 2026-09-04
started_at:
completed_at:
completion_pr:
merge_sha:
---

# Chronicle Studio Imports and Progress

## Canonical scope

GitHub Issue #499 is the executable specification.

## Goal

Provide the single administrator with functional Studio document/import operations, job progress, failure inspection, retry/resume and cancellation.

## Acceptance

- [ ] Document -> Revision -> Ingestion Job works through Studio.
- [ ] import list/detail reflects durable job/stage/chunk state.
- [ ] bounded polling updates progress across reload/restart.
- [ ] failed chunks/attempt history are inspectable without secrets.
- [ ] retry/resume/cancel preserve control-plane invariants.
- [ ] revision/supersession history remains visible.
- [ ] Studio browser/API integration tests pass.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
