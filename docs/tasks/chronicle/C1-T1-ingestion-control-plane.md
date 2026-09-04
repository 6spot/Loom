---
task: C1-T1
issue: 490
status: completed
depends_on: [C0-T12]
created_at: 2026-09-04
started_at: 2026-09-04
completed_at: 2026-09-04
completion_pr: 509
merge_sha: f67d5218696d2d118522b2a03e3850c84f4c7106
---

# Chronicle Document Ingestion Control Plane

## Canonical scope

GitHub Issue #490 is the executable specification. This record tracks durable status/evidence only.

## Goal

Freeze Chronicle-owned Document/Revision/IngestionJob/Stage/Section/Chunk/ChunkRun/Review/Output contracts, persistence, and legal lifecycle transitions without changing C0 historical authority.

## Authority boundary

Application-owned persistence only. Existing C0 staged, Resolution and canonical publication layers remain unchanged. New Loom authority requires an Architecture Amendment.

## Acceptance

- [x] C1 control-plane design and PostgreSQL migration exist.
- [x] immutable revision/supersession semantics are enforced.
- [x] job/stage/chunk/review provenance is auditable.
- [x] Rust lifecycle transition tests cover retry/review/completion.
- [x] deterministic fake restart/checkpoint lifecycle passes.
- [x] C0 persistence semantics and PostgreSQL 18 regressions remain green.
- [x] Rust/Python ownership boundary is documented.
- [x] applicable CI/governance checks pass.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-04 — Implementation started: additive migration `0002_chronicle_c1_control_plane.sql`, Python store `persistence/control_plane.py`, standalone Rust contract crate `control_plane/`, PG lifecycle tests, and `docs/control-plane.md`. No Loom authority change; Amendment 0006 boundary kept.
- 2026-09-04 — Reviewer findings addressed: DB/store invariants enforce output↔revision, chunk↔section, review↔chunk same-job consistency; idempotent output retry returns persisted IDs; parent identity links are immutable while lifecycle fields remain mutable.
- 2026-09-04 — Delivery PR #509 merged as `f67d5218696d2d118522b2a03e3850c84f4c7106`. Exact delivery head `c20e0b8dbe3e65132d2a2fc41acf4eb4c96cd7e6` passed GitHub Actions Chronicle run 33853471138, Chronicle Docker run 33853471095, and CI run 33853471091. Catch-up post-merge reconciliation records the already-delivered task as completed on the canonical ledger.
