---
task: M5-T5
issue: 72
status: planned
depends_on: [68, 70, 71]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M5-T5 — Ancestry-Aware History and Causality

## Goal
Project child history through ancestry and validate cross-Timeline EventRef causality without copying history rows.

## Required implementation
- Traverse multi-generation ancestry with deterministic visible history ordering.
- Child history = visible ancestor history through each fork boundary + branch-local Events.
- Validate current/ancestor EventRef causes and reject sibling, unrelated-World and ancestor-after-fork references.
- Preserve Event ledger immutability and stable cursor/sequence semantics for M6 queries.

## Forbidden shortcuts
No copied/shadow Event ledgers, globally-existing EventId acceptance or sibling traversal.

## Acceptance checklist
- [ ] parent/child/grandchild history ordering is deterministic;
- [ ] valid visible ancestor causes commit;
- [ ] invalid cross-branch/future causes reject;
- [ ] later branch commits do not rewrite another branch history;
- [ ] InMemory/PostgreSQL/restart parity passes;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after fork persistence.
