---
task: M7-T4
issue: 85
status: planned
depends_on: [83]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M7-T4 — Claim-Next Due Work Contract

## Goal
Let workers discover and atomically claim executable Durable Work without knowing WorkId in advance.

## Required implementation
- Runtime-owned claim-next port returns Timeline target + WorkClaim + WorkRecord.
- Eligibility requires Pending, retry availability at platform now, no live lease, and due World Time <= Timeline World Time.
- PostgreSQL uses concurrency-safe row locking (`FOR UPDATE SKIP LOCKED`/equivalent) and existing fencing semantics.
- Define deterministic selection ordering; InMemory models same conflict/lease behavior.
- Claim is platform operation: no Event, TimelineVersion or logical history advance.

## Forbidden shortcuts
No scan-then-claim race, platform-time-as-World-time, claim World Event or process mutex substituting for DB safety.

## Acceptance checklist
- [ ] only due/available Work is selected;
- [ ] concurrent workers cannot claim same live lease;
- [ ] expired lease reclaim/stale fencing pass;
- [ ] future World-time Work is skipped;
- [ ] ordering/starvation behavior is tested;
- [ ] adapter/PostgreSQL concurrency parity passes.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after Reaction scheduling.
