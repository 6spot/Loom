---
task: M10-T5
issue: 191
status: completed
depends_on: [160, 164, 183, 190]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at: 2026-08-24
completion_pr: 246
merge_sha: 39a429fdbb52df6c037baa10f47d6de38ac5492a
---
# M10-T5 — Agency Wake scheduling, CAS policy and resumability

- Schedule/cancel AgencyWake through existing Durable Work model; no second queue/timer/table.
- WorkTarget carries Agent/cognition requirement explicitly; no fake handler/payload convention.
- Restart/fence/retry/fork use M5/M6 semantics; fork gives new WorkId, same semantic target/due/order, reset operational state.
- Slow cognition that loses TimelineVersion/fence did not become truth; at most one result wins.
- V0 default CAS policy is **resample** unless an explicitly configured deterministic/reusable policy exists. Reuse vs resample is ExecutionPolicy + provenance, never implicit.
- Any reused Decision must be revalidated under fresh pinned version/Binding/Action authority.
- Track discarded cognition/cost metadata without secrets.

## Acceptance
- [x] Wake survives restart and is head-admitted.
- [x] Stale claim/CAS cannot duplicate Agent mutation.
- [x] Reuse/resample policy is explicit/provenance-visible.
- [x] Fork preserves semantic Wake/reset operations.
- [x] Discarded cognition is measurable.
- [x] PostgreSQL concurrency + standard gates pass.

Architecture: A0003 §§3.1/3.6/5/7.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.