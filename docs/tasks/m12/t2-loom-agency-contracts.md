---
task: M12-T2
issue: 122
status: planned
depends_on: [121]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M12-T2 — Implement `loom-agency` Contracts

## Goal
Turn the Agency skeleton into the stable extension SPI/value layer frozen by #121.

## Required implementation
- Add documented Agent/View/Context/CognitiveRequest/Decision/CognitiveExecutor/CognitiveError/ExecutionPolicy types.
- Keep Cargo dependencies to Core/Protocol only as required.
- Executor interface stays provider/runtime-neutral and carries only audit-safe metadata.
- Type design prevents cognitive output from directly expressing commit authority.

## Forbidden shortcuts
No vendor SDK, BaseWorldView alias, Runtime types in public Agency or Event/Effect output from executor.

## Acceptance checklist
- [ ] complete #121 contracts exist;
- [ ] Cargo DAG passes;
- [ ] Decision can only Act/NoAction per V0;
- [ ] metadata is provenance-safe/secret-free;
- [ ] public docs explain authority/visibility;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after #121.
