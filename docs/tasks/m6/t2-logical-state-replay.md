---
task: M6-T2
issue: 163
status: planned
depends_on: [154, 162]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M6-T2 — Replay Timeline Logical State

- Replay Logical Journal to exact committed `TimelineVersion`.
- Reconstruct World Time, logical Work lifecycle/target/due/order, and chronology-budget position.
- Combine with M6-T1 materialization for historical reconstruction.
- Never reconstruct lease/fence/attempt/backoff/error as semantic history.
- Support initial version and Event-only/Work-only/time-only versions; reject gaps/inconsistency.

## Acceptance
- [ ] Historical Pending Work intervals are exact.
- [ ] World Time comes only from time transitions.
- [ ] Budget/order restore exactly after restart.
- [ ] Operational retry noise cannot change reconstruction.
- [ ] InMemory/PostgreSQL parity + standard gates pass.

Architecture: `world-runtime.md`; A0002 §3.

## Verification evidence
Pending.