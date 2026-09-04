---
task: C1-T4
issue: 493
status: planned
depends_on: [C1-T1, C1-T2]
created_at: 2026-09-04
started_at:
completed_at:
completion_pr:
merge_sha:
---

# Chronicle Durable Ingestion Worker

## Canonical scope

GitHub Issue #493 is the executable specification.

## Goal

Add a restart-safe PostgreSQL-backed ingestion worker with leases, checkpoints, retry/resume/cancel semantics and no external queue dependency.

## Acceptance

- [ ] queued jobs have one active lease winner.
- [ ] independent jobs can run concurrently without duplicate work.
- [ ] crash/restart safely reclaims expired work.
- [ ] succeeded stages/chunks are skipped on resume.
- [ ] retries append ChunkRun attempts rather than overwrite evidence.
- [ ] cancellation preserves completed checkpoints.
- [ ] authenticated Studio APIs expose lifecycle controls.
- [ ] no Redis/Celery/RabbitMQ is required.
- [ ] PostgreSQL 18 restart/concurrency checks pass.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
