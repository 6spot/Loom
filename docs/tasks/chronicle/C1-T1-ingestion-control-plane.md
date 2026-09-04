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
- 2026-09-04 — Implementation started: additive migration `0002_chronicle_c1_control_plane.sql`,
  Python store `persistence/control_plane.py`, standalone Rust contract crate
  `control_plane/` (zero deps, own workspace), PG lifecycle tests, and
  `docs/control-plane.md`. No Loom authority change; Amendment 0006 boundary kept.
- 2026-09-04 — Reviewer FAIL D-1/D-2 addressed: DB triggers + store pre-checks
  enforce output↔revision, chunk↔section, review↔chunk same-job invariants;
  `record_output` retries return the persisted row ID; 3 new PG tests added.
- 2026-09-04 — Reviewer FAIL D-3 addressed: generic `forbid_identity_remap`
  trigger freezes parent identity links (jobs/sections/chunks/runs/reviews/
  outputs) after insert while lifecycle columns stay mutable; 1 new PG
  regression test added.
