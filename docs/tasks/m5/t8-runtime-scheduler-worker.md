---
task: M5-T8
issue: 160
status: in_review
depends_on: [156, 157]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at:
completion_pr:
merge_sha:
---
# M5-T8 — Resumable Scheduler worker and executor topology

## Contract
- Runtime step chooses/admit/claims independent Timeline heads, starts root Work Session, executes target-specific semantics, validates and atomically completes/retries/terminalizes.
- Long-running polling/process lifecycle is Application-owned; semantic next-Work/time decision remains Runtime-owned.
- Choose one concrete Linux v0 executor/topology and coherently audit API futures, Runtime ports, Capability/Agency SPIs, Storage futures and shared state for Send/Sync requirements.
- Multi-process correctness comes from PostgreSQL fencing + CAS, not shared mutex.
- Bound concurrency/polling/leases/shutdown; hold no DB authority transaction during resolver/cognition.

## Acceptance
- [ ] Independent Timelines execute concurrently; same Timeline remains head/CAS serialized.
- [ ] Kill-after-claim recovers after lease expiry.
- [ ] Graceful shutdown stops new claims safely.
- [ ] Topology/Send/Sync audit documented.
- [ ] PostgreSQL stress + standard gates pass.

Architecture: Amendment 0001 §3; Amendment 0003 §§5/7.

## Verification evidence
- `apps/loom-server` provides one `Runtime` plus one `TimelineTarget` per
  application-owned worker, bounded polling, external graceful shutdown, and
  supervisor-owned restart/error handling without adding `Send`/`Sync` to
  executor-neutral Runtime futures.
- `docs/development/runtime-worker.md` records the current-thread v0 topology,
  complete Send/Sync audit boundary, resolver/cognition transaction boundary,
  head-aware same-Timeline rule, and PostgreSQL fencing/CAS recovery model.
- `postgres_work` runs the independent-Timeline worker-instance concurrency
  scenario plus same-Timeline claim/fence, non-head admission, expiry/reclaim,
  terminalization, completion-race, and durable-budget restart scenarios.
- `cargo fmt --all -- --check`, `git diff --check`,
  `python3 tools/check_architecture.py`, and
  `CARGO_INCREMENTAL=0 RUSTFLAGS='-C debuginfo=0' cargo clippy -p loom-server
  --all-targets -- -D warnings` pass.
- `CARGO_INCREMENTAL=0 RUSTFLAGS='-C debuginfo=0' cargo test -p loom-server`
  passes 2 unit tests and `cargo test -p loom-runtime --lib` passes 31 tests.
- `CARGO_INCREMENTAL=0 RUSTFLAGS='-C debuginfo=0' cargo test --workspace
  --all-features` passes the workspace unit, integration, and doc tests,
  including all 11 `postgres_work` tests against the repository PostgreSQL 18
  service.
