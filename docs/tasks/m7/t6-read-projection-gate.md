---
task: M7-T6
issue: 173
status: planned
depends_on: [168, 169, 170, 171, 172]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M7-T6 — Read/projection/blob authority gate

Across parent/child Timelines and multiple bindings: exercise catalogs, trajectory/causal queries, projection build/query/delete/rebuild, blobs and a long pinned read racing a commit.

## Assertions
- [ ] World Catalog never exposes disabled semantics as executable.
- [ ] History/causal visibility respects ancestry and bounds.
- [ ] Projection changes cannot change authority/replay/fork.
- [ ] Semantic ReadSet records projection dependency.
- [ ] Missing/corrupt blob changes only blob access.
- [ ] Pinned reads remain one-version consistent without full-World PostgreSQL load.
- [ ] Benchmark limits/evidence are recorded without unsupported scale claims.
- [ ] Architecture/fmt/check/clippy/tests/rustdoc + PostgreSQL18/pgvector/blob suites pass.

## Verification evidence
Pending.