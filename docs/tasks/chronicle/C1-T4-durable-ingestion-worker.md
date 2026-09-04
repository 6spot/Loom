---
task: C1-T4
issue: 493
status: completed
depends_on: [C1-T1, C1-T2]
created_at: 2026-09-04
started_at: 2026-09-04
completed_at: 2026-09-04
completion_pr: 513
merge_sha: d774b662d9cc538501ab780902cd39e5eef0c818
---

# Chronicle Durable Ingestion Worker

## Canonical scope

GitHub Issue #493 is the executable specification.

## Goal

Add a restart-safe PostgreSQL-backed ingestion worker with leases, checkpoints, retry/resume/cancel semantics and no external queue dependency.

## Acceptance

- [x] queued jobs have one active lease winner.
- [x] independent jobs can run concurrently without duplicate work.
- [x] crash/restart safely reclaims expired work.
- [x] succeeded stages/chunks are skipped on resume.
- [x] retries append ChunkRun attempts rather than overwrite evidence.
- [x] cancellation preserves completed checkpoints.
- [x] authenticated Studio APIs expose lifecycle controls.
- [x] no Redis/Celery/RabbitMQ is required.
- [x] PostgreSQL 18 restart/concurrency checks pass.

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
- 2026-09-04 — Reviewer FAIL D-1/D-2/D-3 addressed on PR 513: the worker
  now runs every database step in its own short committed transaction
  (`JobRunner`; no transaction held across executor work), so Studio
  cancel never blocks and expired leases stay reclaimable; each durable
  transition commits before proceeding, so checkpoints are visible
  mid-run; every worker mutation is lease-fenced (`LeaseLost` halts stale
  execution) with a strict heartbeat. 4 focused regression tests added
  (cancel-during-execution, mid-run checkpoint visibility,
  takeover-halts-stale, store-level fencing). Full local verification
  re-run green.
- 2026-09-04 — Reviewer PASS on re-review (no remaining D-*); delivery
  PR 513 merged as d774b662d9cc538501ab780902cd39e5eef0c818. Post-merge
  reconciliation: status completed with actual PR/merge evidence, all
  acceptance boxes checked. Verification evidence: worker 17, Studio
  sidecar 7, persistence 39, read_api 36 PG tests; Rust server 20 +
  control-plane 10 tests; clippy/fmt, storage-ownership check, Compose
  config, and GitHub Chronicle PostgreSQL 18 + Docker checks green.
