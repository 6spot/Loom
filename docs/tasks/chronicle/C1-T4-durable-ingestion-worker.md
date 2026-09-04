---
task: C1-T4
issue: 493
status: in_progress
depends_on: [C1-T1, C1-T2]
created_at: 2026-09-04
started_at: 2026-09-04
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
- 2026-09-04 — Implementation: standalone Python worker
  `apps/chronicle/worker/ingestion_worker.py` (claim via `FOR UPDATE
  SKIP LOCKED`, expiring leases + heartbeat, graceful shutdown,
  checkpoint-skipping resume, append-only ChunkRuns, bounded retry,
  cancellation, deterministic fake stage/chunk executors); store lifecycle
  ops `cancel_job`/`retry_job`/`resume_job`/`list_jobs`/`get_job_detail`
  in `persistence/control_plane.py` (claim also picks up `running` jobs
  with missing leases after retry/resume); Studio job endpoints
  `read_api/studio_jobs.py` wired into the sidecar and the Rust
  `chronicle-server` Studio namespace (`/api/v1/studio/jobs*`, auth-gated
  proxy); `docs/worker.md` records concurrency limits and why no
  Redis/Celery/RabbitMQ is required; Compose gains an opt-in
  `chronicle-worker` (profile `worker`); Chronicle CI covers the new
  worker/sidecar suites. Verification green locally: worker 13 tests,
  studio-jobs 7 tests, persistence 39 tests, read_api 36 tests, Rust
  server 20 + control-plane 10 tests, clippy/fmt, storage-ownership
  check, Compose config. Delivery PR pending; task stays `in_progress`
  until merge + post-merge reconciliation per `task-completion.md`.
