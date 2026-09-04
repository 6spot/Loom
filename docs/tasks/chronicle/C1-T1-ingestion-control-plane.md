---
task: C1-T1
issue: 490
status: planned
depends_on: [C0-T12]
created_at: 2026-09-04
started_at:
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
