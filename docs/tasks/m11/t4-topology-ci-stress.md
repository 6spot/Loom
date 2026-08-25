---
task: M11-T4
issue: 196
status: completed
depends_on: [180, 194, 195]
created_at: 2026-08-22
started_at: 2026-08-25
completed_at: 2026-08-25
completion_pr: 272
merge_sha: 010571b943d9be60b2892eaae15cfd97909dde14
---
# M11-T4 — Worker/executor stress + Linux CI hygiene

- Stress independent Timeline heads, Actions, Scheduler Work, Ingress and Agency; prove Session/context/provenance isolation.
- Kill/restart around claims/commits/Session/Ingress/SSE/cognition; stale fences/CAS losers harmless.
- Audit coherent Send/Sync requirements across API futures, Runtime ports, Capability/Agency SPIs, Storage adapters and app state; no isolated alias patch as proof.
- Ubuntu/Linux is required CI baseline; remove/avoid required macOS jobs.
- Safe path filtering lets docs/task-only changes skip irrelevant expensive Rust/PostgreSQL work while relevant code/config/migration/test/workflow changes run mandatory gates.
- No disposable verifier workflows.

## Acceptance
- [x] Multi-worker/process stress preserves authority invariants.
- [x] Restart failures recover deterministically.
- [x] Coherent topology compiles/runs and is documented.
- [x] CI path filtering/macOS removal is correct.
- [x] Relevant-code mandatory gates remain enforced.

Architecture: A0002 §4; A0003 §7.

## Implementation candidate

- `crates/loom-storage/tests/postgres_work.rs` adds a deterministic four-worker
  PostgreSQL topology gate. A fixed start barrier releases one current-thread
  executor per independent Timeline; each worker uses its own Runtime,
  Session identity and authority handle. The gate verifies completed Work,
  terminal Sessions, pinned World/Timeline assembly and no cross-worker Event
  or call provenance.
- `apps/loom-server/src/lib.rs` adds compiler-backed `Send + Sync` assertions
  for the HTTP/SSE-owned `ApplicationApi`, clock, entropy and shutdown state.
  `SchedulerWorker` and Runtime remain intentionally executor-local.
- `docs/development/runtime-worker.md` records the complete current-thread
  boundary and the deterministic restart/fault evidence matrix.
- `.github/workflows/ci.yml` keeps one Ubuntu/Linux authoritative workflow,
  has no macOS job, and triggers on all Rust/config/migration/test/tool,
  Compose/Docker and workflow paths. Markdown/task-only changes are outside
  the positive path set and therefore skip the expensive gates.

## Verification evidence

- `cargo test -p loom-storage --test postgres_work --no-run` — passed;
  topology test compiles.
- `bash tools/postgres-test.sh up` — PostgreSQL 18 test service healthy.
- `cargo test -p loom-storage --test postgres_work postgres_18_worker_topology_keeps_sessions_and_provenance_isolated -- --nocapture` — passed;
  four deterministic worker instances completed with isolated Session and
  provenance assertions.
- `cargo test -p loom-server` — passed; transport boundary assertions and
  current-thread worker tests passed.
