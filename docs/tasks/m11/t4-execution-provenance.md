---
task: M11-T4
issue: 116
status: planned
depends_on: [84, 92, 115]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M11-T4 — Durable Execution Provenance Graph

## Goal
Persist Runtime execution evidence so sessions can be explained without parsing logs.

## Required implementation
- Add provenance storage for capability implementation/version refs, subresolution edges, ReadSet dependencies, semantic query revision/results, entropy samples and origin/current Work refs.
- Preserve deterministic ordering/indexes and audit-safe identifiers only.
- Runtime-owned persistence contract; storage does not invent provenance semantics.
- Record rejected/failed/no-change sessions according to lifecycle while distinguishing them from committed mutation.
- InMemory/PostgreSQL parity.

## Forbidden shortcuts
No free-form log blob as sole evidence, causal tables reused for provenance, semantic read evidence dropped or storage introspection inventing metadata.

## Acceptance checklist
- [ ] Action/Work/Ingress origins + implementation refs persist;
- [ ] ReadSet/semantic dependencies round-trip;
- [ ] subresolution/entropy evidence round-trips deterministically;
- [ ] rejected/failed/no-change states are distinguishable;
- [ ] secrets are excluded;
- [ ] restart/adapter/architecture gates pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after session binding and prior entropy/semantic-read foundations.
