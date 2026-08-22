---
task: M5-T5
issue: 157
status: planned
depends_on: [154, 156]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M5-T5 — Chronology Budget, quiescence and World-Time driver

## Contract
- Chronology consumption is Timeline Logical State scoped to WorldInstant and survives process/session/lease changes.
- Minimum v0 unit: each successful Scheduler Work logical completion at same WorldInstant consumes one unit.
- Exhaustion stops automatic progression and surfaces `ChronologyBudgetExceeded`; it never licenses illegal time advance.
- Any semantically due Pending Work blocks World-Time advance, including backoff/missing implementation.
- Runtime Timeline Driver chooses: execute claimable head, report blocked/exhausted, or explicit monotonic CAS time advance after re-check.
- Time transition is one Logical Commit, no fake Event.

## Acceptance
- [ ] Infinite same-time chain is bounded/observable.
- [ ] Exhaustion cannot bypass quiescence.
- [ ] Backoff/missing implementation blocks time.
- [ ] Restart restores time+budget state.
- [ ] PostgreSQL concurrency + standard gates pass.

Architecture: Amendment 0001 §2; Amendment 0002 §3.

## Verification evidence
Pending.