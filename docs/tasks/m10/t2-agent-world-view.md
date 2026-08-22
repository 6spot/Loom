---
task: M10-T2
issue: 188
status: planned
depends_on: [170, 172, 187]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M10-T2 — Visibility-limited AgentWorldView

- Runtime builds subjective view from Session-pinned reads, explicit local observations, Capability-owned semantic visibility and permitted semantic retrieval.
- Agency owns context shape; Capability owns semantic visibility meaning; Runtime owns orchestration/Binding/budgets/evidence.
- Default visibility is not entire World; hidden authoritative facets/relationships/events stay hidden.
- Semantic retrieval uses M7 Runtime mediation + ReadSet only.
- Bound entities/relationships/events/results/bytes/depth.
- Context must stay at one TimelineVersion and executor receives no BaseWorldView/WorldStore handles.

## Acceptance
- [ ] Allowed state visible; hidden authoritative data inaccessible.
- [ ] Concurrent commit cannot mix context revisions.
- [ ] Retrieval obeys visibility/Binding/budget.
- [ ] Context dependencies appear in provenance.
- [ ] Standard gates pass.

Architecture: A0003 §3.4/§4.

## Verification evidence
Pending.