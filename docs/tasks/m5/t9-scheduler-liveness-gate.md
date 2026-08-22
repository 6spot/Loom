---
task: M5-T9
issue: 161
status: planned
depends_on: [153, 154, 155, 156, 157, 158, 159, 160]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M5-T9 — Scheduler/liveness final gate

## Scenario
Exercise multiple Timelines; At/Immediate Work; same-time ties; Reaction chains; technical failure/backoff; missing implementation; lease expiry; concurrent workers; chronology exhaustion; authorized Dead/Cancelled; entropy; explicit time advancement and restart.

## Required assertions
- [ ] Same-Timeline order is exactly `(effective_due_world_time, logical_schedule_order)` after restart.
- [ ] No later Work passes due head for operational reasons.
- [ ] Independent Timeline heads can run concurrently.
- [ ] Retry changes no World/logical history.
- [ ] Missing implementation consumes no attempt and blocks time visibly.
- [ ] Bounded failure has explicit exit.
- [ ] Chronology state survives restart and cannot permit illegal advance.
- [ ] World Time changes only through explicit quiescent Logical Commit.
- [ ] Reaction ordering/atomicity and entropy evidence pass.
- [ ] Architecture/fmt/check/clippy/tests/rustdoc + PostgreSQL scheduler suites are green.

## Verification evidence
Pending.