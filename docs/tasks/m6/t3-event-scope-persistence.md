---
task: M6-T3
issue: 77
status: planned
depends_on: [75]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M6-T3 — Event Scope Validation and Persistence

## Goal
Carry Event Scope through proposal validation, committed Event representation, both adapters and History filtering.

## Required implementation
- Extend proposed/committed Event values per #75.
- Validate type/owner/schema revision/value/Event-definition constraints before `ValidatedResolution`.
- Add normalized PostgreSQL scope rows/indexes and InMemory parity.
- Preserve scope through history/replay metadata and ancestry-aware filters.

## Forbidden shortcuts
No unvalidated JSON-only scope, transport-specific model, DB-only semantic validation or scope loss during history/replay.

## Acceptance checklist
- [ ] valid scope round-trips;
- [ ] unknown/wrong schema/disallowed scope rejects before commit;
- [ ] fresh PostgreSQL migration/indexes pass;
- [ ] child ancestry scope filtering works;
- [ ] replay retains scope metadata without treating it as State effect;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after #75.
