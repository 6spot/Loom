---
task: M10-T2
issue: 188
status: completed
depends_on: [170, 172, 187]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at: 2026-08-24
completion_pr: 243
merge_sha: 06ea175a42a2a191e700ea409d0defb29ccb7ca0
---
# M10-T2 — Visibility-limited AgentWorldView

- Runtime builds subjective view from Session-pinned reads, explicit local observations, Capability-owned semantic visibility and permitted semantic retrieval.
- Agency owns context shape; Capability owns semantic visibility meaning; Runtime owns orchestration/Binding/budgets/evidence.
- Default visibility is not entire World; hidden authoritative facets/relationships/events stay hidden.
- Semantic retrieval uses M7 Runtime mediation + ReadSet only.
- Bound entities/relationships/events/results/bytes/depth.
- Context must stay at one TimelineVersion and executor receives no BaseWorldView/WorldStore handles.

## Acceptance
- [x] Allowed state visible; hidden authoritative data inaccessible.
- [x] Concurrent commit cannot mix context revisions.
- [x] Retrieval obeys visibility/Binding/budget.
- [x] Context dependencies appear in provenance.
- [x] Standard gates pass.

Architecture: A0003 §3.4/§4.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.