---
task: M5-T5
issue: 157
status: completed
depends_on: [154, 156]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: 219
merge_sha: 2aeff4816d74729bb906a57f7839395e85436d30
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
- [x] Infinite same-time chain is bounded/observable.
- [x] Exhaustion cannot bypass quiescence.
- [x] Backoff/missing implementation blocks time.
- [x] Restart restores time+budget state.
- [x] PostgreSQL concurrency + standard gates pass.

Architecture: Amendment 0001 §2; Amendment 0002 §3.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.