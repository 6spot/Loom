---
task: M11-T1
issue: 113
status: planned
depends_on: [111]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M11-T1 — Runtime Revision and Provenance Contract

## Goal
Freeze separate durable models for platform evolution, root Execution Sessions and execution provenance.

## Implementation contract
- Define `RuntimeRevision`, `ExecutionSession`, `ExecutionOrigin` ownership/lifecycle.
- Revision records include immutable id, publish/activate platform times, core build/ref, capability implementation refs, summary and semantic-change flag without secrets.
- Root Action/Work/Ingress sessions pin exactly one active revision at start.
- Provenance includes origin, ReadSet, subresolution graph, entropy, capability implementation refs and committed EventRefs; cognition metadata attaches later.
- Define transaction/crash guarantees and explicitly separate World causality, execution provenance and Runtime Change history.

## Forbidden shortcuts
No Runtime activation World Event, shared causality/provenance tables, mid-session revision switch or secret config in provenance.

## Acceptance checklist
- [ ] three history graphs are unambiguous;
- [ ] revision/session/origin schemas are frozen;
- [ ] session crash/finalization semantics are explicit;
- [ ] Event/read/entropy/call evidence is defined;
- [ ] focused docs/tests pass;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned as M11 SERIAL ROOT.
