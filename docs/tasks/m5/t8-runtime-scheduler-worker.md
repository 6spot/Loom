---
task: M5-T8
issue: 160
status: planned
depends_on: [156, 157]
created_at: 2026-08-22
started_at:
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
Pending.