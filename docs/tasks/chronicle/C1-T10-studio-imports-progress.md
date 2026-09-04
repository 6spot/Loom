---
task: C1-T10
issue: 499
status: completed
depends_on: [C1-T3, C1-T4, C1-T9]
created_at: 2026-09-04
started_at: 2026-09-04
completed_at: 2026-09-04
completion_pr: 520
merge_sha: f18f2e977195ce9562b7352a8e8b5f05ea3afee9
---

# Chronicle Studio Imports and Progress

## Canonical scope

GitHub Issue #499 is the executable specification.

## Goal

Provide the single administrator with functional Studio document/import operations, job progress, failure inspection, retry/resume and cancellation.

## Acceptance

- [x] Document -> Revision -> Ingestion Job works through Studio.
- [x] import list/detail reflects durable job/stage/chunk state.
- [x] bounded polling updates progress across reload/restart.
- [x] failed chunks/attempt history are inspectable without secrets.
- [x] retry/resume/cancel preserve control-plane invariants.
- [x] revision/supersession history remains visible.
- [x] Studio browser/API integration tests pass.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-04 — Started from canonical `main` after catch-up reconciliation PR #519. Scope is the functional shadcn Studio Imports surface over the existing C1-T3 Document/Revision and C1-T4 Job APIs, plus a safe Studio Job Detail projection that exposes run/version/validation/error metadata without returning T6 verbatim prompts/raw model responses/candidates to the browser. No review decision UI or Reader Presentation is added here.
- 2026-09-04 — Delivery completed with functional `/studio/imports`, `/studio/imports/:jobId`, and `/studio/sources` flows; immutable Revision history, bounded durable Job polling, stage/chunk/run inspection, explicit Retry/Resume/Cancel confirmation, safe model-run metadata projection, and Rust embedded-web routing/assets. Chronicle CI also corrected the committed Vite bundle parity path so production `web/dist` is verified rather than accidentally checking `apps/web/dist`.
- 2026-09-04 — Delivery PR #520 merged as `f18f2e977195ce9562b7352a8e8b5f05ea3afee9`. Exact delivery head `6dba8160ebd3bdc38392f83b85c4776718851f39` passed GitHub Actions CI run 33887054626, Chronicle run 33887054495, and Chronicle Docker run 33887054587, including webapp build/dist parity, C0 browser smoke, Rust front smoke, PostgreSQL contracts, and Docker deployment verification.
