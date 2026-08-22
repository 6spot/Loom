---
task: M4-T2
issue: 62
status: planned
depends_on: [61]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M4-T2 — Pure World Replay Engine

## Goal

Deterministically reconstruct materialized World State from ordered committed Events and their frozen Effects.

## Required implementation

- Add a Runtime-owned pure replay engine over an empty/base Timeline materialization plus ordered committed Events.
- Reconstruct Entity existence, Relationship structure/lifecycle, Facets, World Time and head/Event sequencing required by M4-T1.
- Cover CreateEntity, Create/EndRelationship, Put/RemoveFacet, same-Event structural references, mixed multi-Event ordering and zero-effect Events.
- Reject malformed/non-contiguous/impossible frozen history with typed deterministic replay errors.

## Forbidden shortcuts

- Do not call resolvers, invariants, cognition, entropy or providers.
- Do not fill replay gaps from current materialized State.
- Do not write persistence from the pure replay engine or implement fork here.

## Acceptance checklist

- [ ] all current frozen Effect variants replay correctly;
- [ ] same-Event identity/reference semantics replay correctly;
- [ ] malformed/gapped history fails deterministically;
- [ ] replayed current State equals independently expected materialization;
- [ ] focused composition tests cover mixed sequences;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence

- PR:
- merge SHA:
- verification:

## Progress log

- 2026-08-22 — Planned after #61.
