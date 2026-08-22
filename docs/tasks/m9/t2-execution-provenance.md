---
task: M9-T2
issue: 183
status: planned
depends_on: [170, 182]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M9-T2 — Complete Execution Session provenance

- Persist Session lifecycle/status/platform times/origin/root refs.
- Persist exact Runtime Revision + implementation assembly.
- Persist ordered ReadSet, semantic retrieval evidence, subresolution call graph, entropy samples, policy IDs and current Work/origin refs.
- Failed/rejected/no-change/blocked Sessions remain auditable without fake Events.
- Exclude raw secrets/sensitive provider/auth config and unbounded payload capture.
- Storage serializes Runtime-owned evidence; it does not invent provenance by inspecting implementations.

## Acceptance
- [ ] Action/Work/Ingress/bootstrap evidence round-trips.
- [ ] Read/call/entropy order deterministic.
- [ ] Outcome states distinguishable after restart/revision switch.
- [ ] InMemory/PostgreSQL + standard gates pass.

## Verification evidence
Pending.