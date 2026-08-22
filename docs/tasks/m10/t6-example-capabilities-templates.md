---
task: M10-T6
issue: 110
status: planned
depends_on: [108]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M10-T6 — Neutral Example Capabilities and Templates

## Goal
Add simple architecture-compliant semantics for docs/E2E without binding Engine V0 to a real business domain.

## Required implementation
- Add concrete example Capability crates (e.g. counter/observer) depending only on Core/Protocol/Capability.
- Exercise representative Action/Event/Facet and where useful Relationship/Work/Reaction/SemanticIndex surfaces.
- Add at least two Templates with distinct enabled capability sets/bootstrap recipes.
- Wire examples into server only at composition root and document unified API use.

## Forbidden shortcuts
No Runtime/Storage/Boundary dependency from Capability, hidden mutation/test APIs, production-domain policy baseline or Template enabling all installed capabilities implicitly.

## Acceptance checklist
- [ ] example crate DAG passes;
- [ ] two Templates resolve distinct exact sets;
- [ ] representative semantics execute through normal authority;
- [ ] server wiring is composition-only;
- [ ] docs use unified API;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned; parallel-safe after bootstrap contract.
