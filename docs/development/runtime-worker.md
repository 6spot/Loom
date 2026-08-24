# v0 Runtime worker topology

`loom-runtime` owns one bounded semantic step: `Runtime::drive_timeline`. The
step reads the current Timeline, selects the persistent logical head, checks
semantic due-ness and operational claimability, and delegates claim/fence,
resolver execution, validation, completion/retry/terminalization and
World-Time CAS to the Runtime/Storage authority boundary.

The v0 Linux topology is deliberately small:

```text
one Linux worker process
  └── one single-thread executor
        └── one Runtime instance
              └── application-owned SchedulerWorker
                    └── bounded calls to Runtime::drive_timeline

independent Linux worker processes
  └── independent Runtime instances
        └── shared PostgreSQL authority
              └── head-aware claim/fence + TimelineVersion CAS
```

`apps/loom-server` provides the application composition helper. It accepts an
application clock and operational lease/retry durations, checks an external
shutdown signal before every step, and exposes a caller-supplied poll bound.
Polling cadence, process restart, retry of infrastructure errors and process
supervisor policy remain application-owned. Rebuilding a worker creates a new
Runtime instance; no Runtime-global mutex or restart marker is required.

The helper has no `Send`/`Sync` bounds for Runtime, persistence futures,
Capability registry objects, resolver/handler SPI or Agency contracts. The
current-thread executor is the v0 contract. Do not add `Send` to an isolated
future alias as a substitute for auditing the complete topology. A future
multi-threaded Runtime or shared-process topology requires a new coherent
audit across API futures, Runtime ports, Capability/Agency SPI, Storage
adapters and worker ownership.

## Send/Sync audit boundary

The compiler-checked boundary for the current topology is:

| Surface | Boundary | Owner |
| --- | --- | --- |
| `loom_api::ApiFuture` / `AdminFuture` | executor-neutral, no `Send` bound | Boundary adapter / current request task |
| Runtime `PersistenceFuture`, Capability semantic futures and Agency `CognitiveFuture` | executor-neutral, no `Send` bound | the worker's current-thread executor |
| Capability `Invariant`, `ActionResolver` and `WorkHandler` objects | `Send + Sync` SPI objects; returned futures remain executor-neutral | Capability registry and worker |
| `loom-storage::PgStorage` and its SQLx pool | shared `Send + Sync` authority handle | independent Linux processes/workers |
| HTTP/SSE `BoundaryApi` and `ApplicationApi` | `Send + Sync + 'static` | transport composition root |
| `SchedulerWorker` / `Runtime` | no blanket `Send`/`Sync` requirement | one current-thread executor per process |

`apps/loom-server` contains a compile-time `Send + Sync` assertion for the
transport-owned state. This keeps the required HTTP boundary visible while
preserving the executor-neutral Runtime and persistence contracts. The
boundary's `block_on_api` adapter is the only place that bridges those
non-`Send` futures into the multithread HTTP composition.

## Lifecycle rules

- The application checks its shutdown signal before each new Runtime step. An
  active step is allowed to finish, so graceful stop does not revoke a live
  claim or abandon a commit midway.
- The application bounds each polling run and owns any sleep between calls.
  `WorkerStopReason::PollLimitReached` is a normal handoff to the caller.
- A process fault or returned infrastructure error ends the current worker
  run. The supervisor may rebuild the Runtime from PostgreSQL and apply its
  bounded restart policy.
- A crash after claim leaves the Work `Pending` with an operational lease.
  Lease expiry permits a later worker to reclaim it with a newer fence; a
  stale fence cannot retry, complete or terminalize the Work.
- A semantically due head cannot be skipped to reach a later Work on the same
  Timeline. PostgreSQL `SKIP LOCKED` is used only to distribute work across
  independent Timeline authority domains.
- Resolver and cognition code runs outside the authority transaction. The
  final completion still validates the claim fence and pinned
  `TimelineVersion` at the logical commit point.

## Audit evidence

The worker crate's current-thread tests compile and run `SchedulerWorker` with
the existing executor-neutral Runtime futures. PostgreSQL tests in
`loom-storage` cover the authority properties used by independent workers:

- concurrent same-Work claims have one fence winner;
- an expired claim is reclaimable and the stale fence cannot retry;
- a non-head Work claim is rejected without mutation;
- scheduler completion and Timeline CAS are race-safe;
- logical chronology budget survives storage restart.

The standard PostgreSQL procedure is documented in
`docs/development/postgres-tests.md`.

## M11-T4 deterministic stress evidence

The topology gate keeps the worker start barrier and all identities fixed; it
does not use random sleeps or an unseeded scheduler. Four independent
current-thread worker executors drive four independent Timeline heads against
one PostgreSQL authority and then verify Work completion, terminal Session
state, pinned World/Timeline assembly and empty cross-worker provenance. The
focused test is
`crates/loom-storage/tests/postgres_work.rs::postgres_18_worker_topology_keeps_sessions_and_provenance_isolated`.

The wider restart/fault matrix remains split at its existing authority
boundaries so each failure window is deterministic and independently
replayable:

- claim/reclaim and stale completion: `postgres_work_stale_completion`;
- commit/CAS and Session finalization: `postgres_work` and
  `postgres_vertical`;
- Ingress acceptance, fence recovery and reopen: `postgres_ingress`;
- cognitive CAS loss, resample/reuse and Agency provenance: the M10 Agency
  gate plus the PostgreSQL Agency tests;
- SSE acknowledgement/resume after restart: `postgres_restart_resume`.

This split is intentional: process death is modelled by dropping and
rebuilding the owning adapter/Runtime while PostgreSQL remains the authority;
no test adds a second in-process lock, checkpoint or restart marker.
