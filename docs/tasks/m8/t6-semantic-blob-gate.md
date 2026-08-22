---
task: M8-T6
issue: 94
status: planned
depends_on: [89, 90, 91, 92, 93]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M8-T6 — Semantic Projection and Blob Gate

## Goal
Prove vectors/blobs are useful facilities but cannot become hidden World authority.

## Required verification
Build/query semantic projections and ReadSet evidence, delete/rebuild under a new revision and prove Event/State/replay/fork unchanged. Store/read blobs, verify hash integrity and typed missing/corrupt/unavailable behavior while World history remains intact. Run fresh PostgreSQL 18 + pgvector and blob adapter contracts.

## Acceptance checklist
- [ ] projection rebuild/remove does not mutate World authority;
- [ ] semantic budgets/ReadSet pass;
- [ ] blob integrity/missing contracts pass;
- [ ] replay/fork do not require vector rows/blob bodies;
- [ ] implementation types do not leak architecture boundaries;
- [ ] final architecture/fmt/check/clippy/tests/rustdoc/pgvector/blob candidate is green.

## Completion evidence
- PR:
- merge SHA:
- final candidate / CI:

## Progress log
- 2026-08-22 — Planned as M8 SERIAL GATE.
