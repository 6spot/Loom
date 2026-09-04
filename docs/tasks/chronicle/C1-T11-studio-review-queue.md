---
task: C1-T11
issue: 500
status: in_progress
depends_on: [C1-T8, C1-T9]
created_at: 2026-09-04
started_at: 2026-09-04
completed_at:
completion_pr:
merge_sha:
---

# Chronicle Studio Review Queue

## Canonical scope

GitHub Issue #500 is the executable specification.

## Goal

Expose durable uncertain Entity/Event resolution decisions to the single administrator without converting model confidence into identity authority.

## Acceptance

- [ ] open ReviewItems are visible with source/job context.
- [ ] all supported C0 Entity/Event decisions can be submitted.
- [ ] administrator choice remains auditable beside model suggestion/rationale.
- [ ] blocked jobs resume only through legal server-side transitions.
- [ ] `uncertain` remains first-class and never forces merge.
- [ ] resolved history survives restart.
- [ ] Studio browser/API integration tests pass.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-04 — Started from canonical `main` after C1-T10 reconciliation. T11 reuses the C1-T8 durable `review_items` + `resolve_resolution_review()` authority and the existing control-plane `resume_job()` gate. Scope is a purpose-built authenticated Review list/detail/decision projection plus Studio UI; no new resolution vocabulary, confidence auto-accept, or generic review framework is introduced.
