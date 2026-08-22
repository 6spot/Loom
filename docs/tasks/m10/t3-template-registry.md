---
task: M10-T3
issue: 107
status: planned
depends_on: [105, 106]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M10-T3 — Template Registry and Assembly Validation

## Goal
Version Templates and validate requested Capability assembly/bootstrap recipes before World creation begins.

## Required implementation
- Define Template values/registry for id/revision/description/capability ranges/config/initial time/bootstrap Actions.
- Validate existence, Loom compatibility, dependency closure, versions, duplicates, config/schema and bootstrap Action ownership against CapabilityRegistry.
- Produce a frozen exact resolved assembly for Runtime creation.
- Expose Template discovery through unified API without executable registry objects.
- Keep Template metadata separate from World Event State and preserve deterministic error ordering.

## Forbidden shortcuts
No bypass of registry validation, dynamic plugin ABI, Template update mutating existing Worlds or resolver exposure.

## Acceptance checklist
- [ ] valid Template resolves exact assembly;
- [ ] missing/incompatible/cyclic/duplicate cases fail before creation;
- [ ] bootstrap/config errors are deterministic;
- [ ] discovery exposes metadata only;
- [ ] multiple revisions coexist;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after World binding.
