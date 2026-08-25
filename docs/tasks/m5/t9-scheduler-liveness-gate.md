---
task: M5-T9
issue: 161
status: completed
depends_on: [153, 154, 155, 156, 157, 158, 159, 160]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: 221
merge_sha: 4090c437adea9b444dfa6e344c677e45a5a9b41a
---
# M5-T9 — Scheduler/liveness final gate

## Scenario
Exercise multiple Timelines; At/Immediate Work; same-time ties; Reaction chains; technical failure/backoff; missing implementation; lease expiry; concurrent workers; chronology exhaustion; authorized Dead/Cancelled; entropy; explicit time advancement and restart.

## Required assertions
- [x] Same-Timeline order is exactly `(effective_due_world_time, logical_schedule_order)` after restart.
- [x] No later Work passes due head for operational reasons.
- [x] Independent Timeline heads can run concurrently.
- [x] Retry changes no World/logical history.
- [x] Missing implementation consumes no attempt and blocks time visibly.
- [x] Bounded failure has explicit exit.
- [x] Chronology state survives restart and cannot permit illegal advance.
- [x] World Time changes only through explicit quiescent Logical Commit.
- [x] Reaction ordering/atomicity and entropy evidence pass.
- [x] Architecture/fmt/check/clippy/tests/rustdoc + PostgreSQL scheduler suites are green.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.