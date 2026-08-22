---
task: M10-T5
issue: 191
status: planned
depends_on: [160, 164, 183, 190]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
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
- [ ] Wake survives restart and is head-admitted.
- [ ] Stale claim/CAS cannot duplicate Agent mutation.
- [ ] Reuse/resample policy is explicit/provenance-visible.
- [ ] Fork preserves semantic Wake/reset operations.
- [ ] Discarded cognition is measurable.
- [ ] PostgreSQL concurrency + standard gates pass.

Architecture: A0003 §§3.1/3.6/5/7.

## Verification evidence
Pending.