---
task: M6-T5
issue: 79
status: planned
depends_on: [72, 77]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M6-T5 — Bounded Causal Graph Queries

## Goal
Expose EventRef lookup, direct causes/effects and bounded recursive traversal with ancestry correctness.

## Required implementation
- Add public `get_event`, direct causes/effects and recursive walk operations.
- Enforce explicit max depth/results/bytes and deterministic dedup/order.
- InMemory and PostgreSQL use EventRef + ancestry rules; PostgreSQL uses recursive CTE/indexes.
- Never cross sibling/unrelated World or ancestor-after-fork boundaries.

## Forbidden shortcuts
No graph database/second authority, unbounded recursion or EventId-only Timeline-agnostic lookup.

## Acceptance checklist
- [ ] direct causes/effects pass;
- [ ] recursive depth/result budgets pass;
- [ ] visible ancestor traversal works;
- [ ] invalid cross-branch traversal is impossible;
- [ ] dedup/order is deterministic;
- [ ] InMemory/PostgreSQL parity passes.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after ancestry and scope foundations.
