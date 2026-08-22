---
task: M5-T4
issue: 156
status: planned
depends_on: [153, 155]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M5-T4 — Logical-head Scheduler admission and claim

## Canonical admission
All must hold: Pending; semantic due; operationally available; no valid conflicting lease; owner enabled by World Binding; target-specific compatible implementation assembled under pinned revision/session; chronology admission permits execution.

## Contract
- Runtime chooses one logical head per Timeline by `(effective_due_world_time, logical_schedule_order)`.
- Storage atomically re-checks and claims that exact head or nothing for that Timeline.
- `SKIP LOCKED` may distribute across independent Timeline heads only; never skip same-Timeline head for later Work.
- Claim is operational only: no TimelineVersion/journal change.
- Multi-process correctness combines head-aware fencing + CAS + transactional head/quiescence re-check.

## Acceptance
- [ ] Lease/backoff/missing software on head cannot let later Work pass.
- [ ] Independent Timelines can claim concurrently.
- [ ] One fence winner per head.
- [ ] PostgreSQL concurrency tests prove no forbidden same-Timeline skip.

Architecture: Amendments 0001 §§3–4/9, 0002 §2, 0003 §3.2.

## Verification evidence
Pending.