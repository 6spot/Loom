# Chronicle durable ingestion worker (C1-T4)

Standalone, restart-safe execution for long-running book ingestion. The
worker is a plain Python process
(`apps/chronicle/worker/ingestion_worker.py`); PostgreSQL 18 is the only
coordinator. There is deliberately no Redis, Celery, RabbitMQ, Kafka, or
any other queue service in this envelope (see "Why no queue service").

## Run

```bash
export CHRONICLE_DATABASE_URL=postgresql://chronicle:...@postgres:5432/chronicle
python3 apps/chronicle/worker/ingestion_worker.py \
  --worker-id worker-01 --lease-seconds 300 --poll-interval 5
```

Flags: `--database-url` (else `CHRONICLE_DATABASE_URL`), `--worker-id`
(default `worker-<host>-<pid>-<rand>`), `--lease-seconds` (default 300),
`--poll-interval` (default 5s), `--max-jobs` (stop after N jobs; default
runs until SIGTERM/SIGINT), `--fail-stage STAGE[:COUNT]` (fault-injection
demos only; never set in production).

Compose ships an opt-in worker service (profile `worker`, not started by
the default stack):

```bash
docker compose -f compose.chronicle.yaml --profile worker up -d chronicle-worker
```

## How durability works

1. **Claim.** `claim_job` takes one `queued` job — or one `running` job
   whose lease expired (crashed worker) or is missing (freshly
   retried/resumed) — with `SELECT ... FOR UPDATE SKIP LOCKED`. At most
   one active lease wins each job; independent jobs are claimed by
   different workers concurrently. The claim commits before execution
   starts.
2. **Execute.** The worker walks the frozen 8-stage pipeline
   (`prepare → structure → segment → extract → assemble → resolve →
   publish → present`). Stages/chunks already `completed` (or `skipped`)
   are never re-run: resume skips succeeded checkpoints by construction.
3. **Short transactions, never across executor work.** Every database
   step runs in its own connection and commits exactly one transaction
   before the worker proceeds. Executor code runs with no transaction
   open, so a slow or hung stage holds no row lock: Studio cancellation
   never blocks on worker activity, and an expired lease row is never
   locked away from a reclaiming worker's `SKIP LOCKED` claim. Each
   committed step is immediately visible to other connections and
   survives a crash at any point.
4. **Lease fencing.** Every worker mutation (`advance_stage_fenced`,
   `set_chunk_status_fenced`, `record_chunk_run_fenced`,
   `set_job_status_fenced`, checkpoint/output writes) predicates on the
   job lease inside the same transaction and raises `LeaseLost` for any
   worker that no longer holds it. Heartbeats are strict: losing the
   lease to a takeover (or to cancellation, which clears the lease)
   halts the stale worker with a `lease_lost` outcome instead of writing
   further state or evidence.
5. **Finish.** After all stages, the worker records one deterministic
   output and moves the job to `completed` (lease cleared). Faults park
   the job in `failed` (bounded Studio retry) or `needs_review` (chunk
   attempts exhausted; a `chunk_failure` review gate owns the job).
   Chunk attempts always append `ingestion_chunk_runs` rows with
   monotonically increasing `attempt`; retries never overwrite prior
   model/debug evidence.
6. **Shutdown.** SIGTERM/SIGINT finishes the current step, then stops.
   The job stays `running` under its lease, so the next live worker
   reclaims it after expiry. Shutdown never marks work failed and never
   invents checkpoints.

## Studio lifecycle operations

Authenticated Studio APIs (Rust `chronicle-server` → Python sidecar →
control-plane store; lifecycle authority stays in the server namespace
plus the control-plane state machine):

```text
POST /api/v1/studio/jobs                         {"revision_id": "..."}
GET  /api/v1/studio/jobs[?status=&limit=&offset=]
GET  /api/v1/studio/jobs/{job_id}
POST /api/v1/studio/jobs/{job_id}/retry    failed -> running (bounded)
POST /api/v1/studio/jobs/{job_id}/resume   needs_review -> running (gated)
POST /api/v1/studio/jobs/{job_id}/cancel   queued/running/needs_review -> cancelled
```

- `retry` refuses jobs that consumed `max_attempts` claim attempts, and
  resets only `failed` stages/chunks to `running`.
- `resume` refuses while any review item is still `open`, and resets only
  `needs_review` stages/chunks.
- `cancel` stops new work immediately; completed checkpoints stay intact.
  Cancelling an already-cancelled job is idempotent.
- Both `retry` and `resume` clear the stale lease so the next live worker
  can claim the job (a `running` job without a lease is claimable).

## Operational concurrency limits

| Bound | Value | Where |
| --- | --- | --- |
| Claim granularity | 1 job per claim, `SKIP LOCKED` | `claim_job` |
| Lease default | 300 s, owner-renewed | `--lease-seconds` |
| Idle poll | 5 s per worker, no thundering herd | `--poll-interval` |
| Job retries | `max_attempts` (default 3) claim attempts | `ingestion_jobs` |
| Chunk retries | `max_attempts` (default 3) per chunk | `ingestion_chunks` |
| Fake topology | 1 section, 2 chunks per job | `FAKE_CHUNKS_PER_JOB` |
| Job bodies | 64 KiB cap on Studio job requests | sidecar |

Scale guidance for the first envelope: run **one worker per 1–2 CPU** up
to a handful of workers on a single host against the Compose PostgreSQL
service. Claims are row-locked and short; heartbeats are one `UPDATE`
per stage/chunk. If claim latency or connection pressure ever becomes the
bottleneck (measured, not presumed), add read-replica-safe polling or
`LISTEN/NOTIFY` wakeups before reaching for external infrastructure.

## Why no queue service is required

- **Ordering/durability already hold.** Jobs, stages, chunks, runs, and
  reviews are rows with auditable transitions, not volatile messages.
  A broker would duplicate this ledger without adding guarantees.
- **Exactly-once execution is a lease, not a queue feature.**
  `FOR UPDATE SKIP LOCKED` plus expiring leases gives single-winner
  claiming and crash reclaim with zero moving parts beyond PostgreSQL,
  which the deployment already runs.
- **Backpressure is the jobs table.** `queued` depth and `failed` /
  `needs_review` counts are directly queryable (`GET /studio/jobs`);
  no separate dead-letter/monitoring system is needed at this scale.
- **Shutdown/restart is stateless.** Workers hold no local queues, so
  any worker may die at any point and the system converges by lease
  expiry alone.

Revisit only on measured evidence: sustained claim contention across
many workers, sub-second scheduling latency requirements, or a
multi-host topology where PostgreSQL connection limits bind first.

## Authority boundary

Application-owned product operations only (Amendment 0006): this worker
and the Studio job endpoints use `CHRONICLE_DATABASE_URL` and
`chronicle.*` tables. They never read or write Loom
Runtime/World/Timeline/Work/Binding state, never model ingestion as Loom
Scheduler Work, and never bypass the C0
staged/resolution/canonical historical-knowledge path.

## Verification

```bash
python3 -m unittest discover -s apps/chronicle/worker -p 'test_*.py' -v
python3 -m unittest discover -s apps/chronicle/read_api -p 'test_studio_jobs*.py' -v
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_*.py'
cd apps/chronicle/server && cargo test --offline
```
