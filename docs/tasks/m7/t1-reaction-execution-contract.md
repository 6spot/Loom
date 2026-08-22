---
task: M7-T1
issue: 82
status: planned
depends_on: [80]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M7-T1 — Reaction Execution Contract

## Goal
Freeze how Event Reactions become durable future Work and what a later Work handler can observe.

## Implementation contract
- Matching Event creates Immediate Work in the same logical/authority commit; handler runs later, never recursively inside commit.
- Define deterministic fan-out ordering/dedup and reaction budget.
- Define static payload rules if supported, plus triggering EventRef/origin Work provenance.
- Define architecture-safe read-only current Work context (WorkId/causal Event/origin) if needed.
- Reaction Work participates in M4 logical history and M5 fork semantics exactly like other Work.

## Forbidden shortcuts
No in-transaction handler execution, post-commit best-effort scheduling, Capability persistence authority or unbounded reaction chains.

## Acceptance checklist
- [ ] atomic scheduling semantics are normative;
- [ ] handler context/origin semantics are frozen;
- [ ] fan-out/dedup/budget rules are explicit;
- [ ] M4/M5 interaction is documented;
- [ ] focused tests/docs pass;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned as M7 SERIAL ROOT.
