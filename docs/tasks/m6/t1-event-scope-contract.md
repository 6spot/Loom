---
task: M6-T1
issue: 75
status: planned
depends_on: [73]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M6-T1 — Event Scope Semantic Contract

## Goal
Define Event Scope as extensible Capability-owned queryable Event metadata without domain-specific Core meanings.

## Required implementation
- Freeze minimum stable Scope identity/value/role mechanism and Capability-owned ScopeDefinition/schema revision/owner metadata.
- Define EventDefinition allowed-scope rules and Runtime ownership/schema/cardinality validation.
- Define normalized public History scope filters while preserving participant/relationship reference semantics.

## Forbidden shortcuts
No `market`/`population`/`country` domain enums in Core, arbitrary unvalidated JSON scope or Capability transport registration.

## Acceptance checklist
- [ ] ownership/type/schema/cardinality rules are normative;
- [ ] Core/Capability/API ownership preserves DAG;
- [ ] Event registration/validation contract is documented;
- [ ] JSON Schema/contract tests pass;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned as M6 SERIAL ROOT.
