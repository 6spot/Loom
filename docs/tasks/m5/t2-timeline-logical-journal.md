---
task: M5-T2
issue: 154
status: planned
depends_on: [153]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M5-T2 — Timeline Logical Journal

## Contract
- Runtime-owned journal records before/after TimelineVersion, explicit World-Time transitions, logical Work schedule/cancel/complete/dead, logical order and chronology-budget consumption.
- Event+State, logical Work and time transitions use the single relevant logical revision.
- Successful Scheduler Work completion and budget consumption are in the same Logical Commit; no extra counter revision.
- Claim/retry/lease/backoff/error changes append no logical history and advance no TimelineVersion.
- PostgreSQL journal persistence is atomic with the authority mutation; provide deterministic historical reads.

## Acceptance
- [ ] Event-only/Work-only/time-only/Event+Work version behavior is exact.
- [ ] Operational retry creates zero journal rows.
- [ ] Rollback keeps authority+journal atomic.
- [ ] Restart reads are deterministic.

Architecture: Amendment 0002 §3; Amendment 0003 §5.

## Verification evidence
Pending.

## Progress Log
- 2026-08-22 — Planned.