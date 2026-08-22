---
task: M10-T1
issue: 105
status: planned
depends_on: [103]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M10-T1 — Template and Per-World Capability Binding Contract

## Goal
Freeze birth-recipe semantics, World Capability Set enforcement and atomic bootstrap behavior.

## Implementation contract
- Installed Capability is distinct from Capability enabled for one World.
- Define Template identity/revision, required capability ranges/config, initial World Time and ordered bootstrap Actions.
- Persist exact Template revision + resolved Capability implementation/version/config with created World.
- Enumerate checks for Action, Work, Reaction, semantic index and Catalog against World binding.
- Bootstrap resolves/validates on ephemeral empty candidate then atomically persists World/Timeline/bindings/Events/State/Work; failure leaves no World.
- Template changes affect only future World creation.

## Forbidden shortcuts
No global-registry-means-enabled, live mutable Template subscription, direct SQL semantic bootstrap or half-created World.

## Acceptance checklist
- [ ] installed/enabled distinction is normative;
- [ ] Template/version/dependency/bootstrap contract is explicit;
- [ ] all enforcement points are enumerated;
- [ ] bootstrap rollback contract is explicit;
- [ ] focused docs/tests pass;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned as M10 SERIAL ROOT.
