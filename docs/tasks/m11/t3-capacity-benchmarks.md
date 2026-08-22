---
task: M11-T3
issue: 195
status: planned
depends_on: [172, 192, 193]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M11-T3 — Scheduler/Agency capacity benchmarks

- Reproducible loads for many Timelines, many same-instant Works, same-instant Agency Wakes with controlled fake latency, external Action races, large-World pinned reads and PostgreSQL head selection.
- Measure throughput/latency/queueing/CAS conflict/lease retry/DB work/discarded cognition and cost metadata.
- Show same-Timeline Scheduler semantic work is head-ordered/serialized while independent Timelines/pre-commit external resolution may overlap.
- Measure default resample and any explicitly allowed reuse policy after cognition CAS conflict.
- Publish environment/data sizes/results; practical readiness claims come from evidence and remain separate from semantic architecture.

## Acceptance
- [ ] Single vs multi-Timeline curves separate.
- [ ] Same-instant serialization visible.
- [ ] Cognition conflict waste quantified.
- [ ] Pinned-read rows/bytes evidence included.
- [ ] Benchmark reproducible; no unsupported scale claim.

## Verification evidence
Pending.