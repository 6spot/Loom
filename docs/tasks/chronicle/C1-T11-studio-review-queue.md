---
task: C1-T11
issue: 500
status: completed
depends_on: [C1-T8, C1-T9]
created_at: 2026-09-04
started_at: 2026-09-04
completed_at: 2026-09-04
completion_pr: 522
merge_sha: d7f167706d6371be0579d1c95a60106df9af77f5
---

# Chronicle Studio Review Queue

## Canonical scope

GitHub Issue #500 is the executable specification.

## Goal

Expose durable uncertain Entity/Event resolution decisions to the single administrator without converting model confidence into identity authority.

## Acceptance

- [x] open ReviewItems are visible with source/job context.
- [x] all supported C0 Entity/Event decisions can be submitted.
- [x] administrator choice remains auditable beside model suggestion/rationale.
- [x] blocked jobs resume only through legal server-side transitions.
- [x] `uncertain` remains first-class and never forces merge.
- [x] resolved history survives restart.
- [x] Studio browser/API integration tests pass.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-04 — Started from canonical `main` after C1-T10 reconciliation. T11 reuses the C1-T8 durable `review_items` + `resolve_resolution_review()` authority and the existing control-plane `resume_job()` gate. Scope is a purpose-built authenticated Review list/detail/decision projection plus Studio UI; no new resolution vocabulary, confidence auto-accept, or generic review framework is introduced.
- 2026-09-04 — Delivery added the authenticated job-scoped `/api/v1/studio/jobs/reviews` list/detail/decision projection, source-attributed staged Entity/Event context, read-only original suggestion/rationale/signals beside durable administrator decisions, exact C0 decision vocabulary enforcement, explicit confirmation, `/studio/review` queue/detail UI, and server-gated Resume through the existing control-plane transition. Real PostgreSQL HTTP tests prove wrong-vocabulary rejection, first-class `uncertain`, audit preservation, restart-durable history, and refusal to resume while review debt remains.
- 2026-09-04 — Delivery PR #522 merged as `d7f167706d6371be0579d1c95a60106df9af77f5`. Exact delivery head `c367bbff603a209ab15f34375145a2d2f317078f` passed GitHub Actions CI run 33889631121, Chronicle run 33889631116, and Chronicle Docker run 33889631087, including PostgreSQL/read-model review contracts, Rust server embedding/routes, webapp build + committed `web/dist` parity, C0 browser smoke, Rust front smoke, and full Docker deployment verification.
