---
task: C1-T1
issue: 490
status: in_progress
depends_on: [C0-T12]
created_at: 2026-09-04
started_at: 2026-09-04
completed_at:
completion_pr:
merge_sha:
---

# Chronicle Document Ingestion Control Plane

## Canonical scope

GitHub Issue #490 is the executable specification. This record tracks durable status/evidence only.

## Goal

Freeze Chronicle-owned Document/Revision/IngestionJob/Stage/Section/Chunk/ChunkRun/Review/Output contracts, persistence, and legal lifecycle transitions without changing C0 historical authority.

## Authority boundary

Application-owned persistence only. Existing C0 staged, Resolution and canonical publication layers remain unchanged. New Loom authority requires an Architecture Amendment.

## Acceptance

- [ ] C1 control-plane design and PostgreSQL migration exist.
- [ ] immutable revision/supersession semantics are enforced.
- [ ] job/stage/chunk/review provenance is auditable.
- [ ] Rust lifecycle transition tests cover retry/review/completion.
- [ ] deterministic fake restart/checkpoint lifecycle passes.
- [ ] C0 persistence semantics and PostgreSQL 18 regressions remain green.
- [ ] Rust/Python ownership boundary is documented.
- [ ] applicable CI/governance checks pass.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-04 — Implementation started (ME-348): Chronicle-owned control-plane
  contract — migration `0002_chronicle_c1_control_plane.sql` (additive over
  frozen C0 tables), `control_plane_store.py` with lease/checkpoint/transition
  guards, standalone Rust domain crate `apps/chronicle/control_plane`
  (frozen vocabularies, transition graph, deterministic fake lifecycle),
  design record `apps/chronicle/docs/ingestion-control-plane.md`, and PG18
  integration tests `test_control_plane_postgres.py`. No Loom
  Core/Runtime/Storage authority touched; Amendment 0006 boundary preserved.
