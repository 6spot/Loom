---
task: M4-T6
issue: 151
status: planned
depends_on: [148, 150]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M4-T6 — Neutral Template / Binding fixtures

## Goal

Provide small non-domain-specific fixtures that exercise birth, Binding and Session semantics and can be reused by later scheduler/replay/Agency gates.

## Implementation contract

- Adapt the neutral counter-style Capability and add only minimal second Capability needed for dependency/binding tests.
- Create at least two versioned Templates with different bindings/bootstrap recipes.
- Include globally installed-but-disabled semantics.
- Cover Action/Event/Facet and declarations needed later for Work/Reaction, without implementing scheduler here.
- Bootstrap Events are normal first Events stamped at initial World Time and attributed to bootstrap Session.
- Keep examples outside Core/Runtime authority layers.

## Acceptance

- [ ] Templates create distinct immutable bindings.
- [ ] Disabled Action cannot execute.
- [ ] New Template revision does not mutate existing World.
- [ ] Bootstrap Session/Revision evidence is observable internally.
- [ ] Architecture + standard gates pass.

## Verification evidence

Pending.

## Progress Log

- 2026-08-22 — Planned.