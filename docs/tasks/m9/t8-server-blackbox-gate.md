---
task: M9-T8
issue: 103
status: planned
depends_on: [96, 97, 98, 99, 100, 101, 102]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M9-T8 — Black-Box Server / Restart / SSE Gate

## Goal
Prove Loom works as a real restartable service from the public network boundary.

## Required verification
Fresh PostgreSQL 18+pgvector/local blob → start server process → create World → Action → query State/History → observe SSE → duplicate idempotent Ingress → persist pending/reaction Work → kill server → restart/resume Work → reconnect SSE cursor → exercise formal HTTP client.

## Forbidden shortcuts
No direct Runtime/store substitute for black-box assertions, in-process-router-only restart test, skipped SSE/Ingress idempotency or test-only routes.

## Acceptance checklist
- [ ] clean startup/migration passes;
- [ ] HTTP World/Action/Query/History/Catalog/Ingress passes;
- [ ] SSE commit/reconnect passes;
- [ ] kill/restart resumes persisted World/Work/Ingress;
- [ ] formal client interop passes;
- [ ] final architecture/fmt/check/clippy/tests/rustdoc/black-box PostgreSQL candidate is green.

## Completion evidence
- PR:
- merge SHA:
- final candidate / CI:

## Progress log
- 2026-08-22 — Planned as M9 SERIAL GATE.
