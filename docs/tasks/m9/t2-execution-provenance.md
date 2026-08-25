---
task: M9-T2
issue: 183
status: completed
depends_on: [170, 182]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at: 2026-08-24
completion_pr: 238
merge_sha: 56755e6659be66e219f47219e62cfc035feccea0
---
# M9-T2 — Complete Execution Session provenance

- Persist Session lifecycle/status/platform times/origin/root refs.
- Persist exact Runtime Revision + implementation assembly.
- Persist ordered ReadSet, semantic retrieval evidence, subresolution call graph, entropy samples, policy IDs and current Work/origin refs.
- Failed/rejected/no-change/blocked Sessions remain auditable without fake Events.
- Exclude raw secrets/sensitive provider/auth config and unbounded payload capture.
- Storage serializes Runtime-owned evidence; it does not invent provenance by inspecting implementations.

## Acceptance
- [x] Action/Work/Ingress/bootstrap evidence round-trips.
- [x] Read/call/entropy order deterministic.
- [x] Outcome states distinguishable after restart/revision switch.
- [x] InMemory/PostgreSQL + standard gates pass.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.