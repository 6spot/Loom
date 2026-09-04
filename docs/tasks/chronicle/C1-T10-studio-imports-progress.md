---
task: C1-T10
issue: 499
status: in_progress
depends_on: [C1-T3, C1-T4, C1-T9]
created_at: 2026-09-04
started_at: 2026-09-04
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
- 2026-09-04 — Started from canonical `main` after catch-up reconciliation PR #519. Scope is the functional shadcn Studio Imports surface over the existing C1-T3 Document/Revision and C1-T4 Job APIs, plus a safe Studio Job Detail projection that exposes run/version/validation/error metadata without returning T6 verbatim prompts/raw model responses/candidates to the browser. No review decision UI or Reader Presentation is added here.
