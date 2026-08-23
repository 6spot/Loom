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
