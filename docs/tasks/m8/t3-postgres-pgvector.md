---
task: M8-T3
issue: 91
status: planned
depends_on: [89, 90]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M8-T3 — PostgreSQL pgvector Projection Storage

## Goal
Add PostgreSQL 18 + pgvector storage/query for rebuildable semantic projections.

## Required implementation
- Add additive `vector` extension/projection migrations with index/source ref, source hash, model/projection revision and vector.
- Validate dimensions/metric against registered index contract.
- Runtime-owned projection ports support insert/upsert/delete/rebuild/query.
- Similarity query has explicit deterministic limit/tie semantics; document approximate-index tradeoffs.
- CI starts from fresh PostgreSQL 18 with pgvector.

## Forbidden shortcuts
No separate vector DB, authoritative vector State, embedding generation in storage or migration rewrites.

## Acceptance checklist
- [ ] fresh migration passes;
- [ ] insert/update/query/delete work;
- [ ] mismatch errors are typed;
- [ ] source/revision metadata round-trips;
- [ ] deleting projection rows leaves Event/State unchanged;
- [ ] pgvector integration/architecture gates pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after #90.
