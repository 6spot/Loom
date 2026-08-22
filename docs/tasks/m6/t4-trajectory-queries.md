---
task: M6-T4
issue: 78
status: planned
depends_on: [72, 77]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M6-T4 — Entity and Relationship Trajectory Queries

## Goal
Expose ancestry-aware trajectories as projections over committed Event associations.

## Required implementation
- Add History API queries for Events involving one Entity or Relationship.
- Define stable ordering/cursor/limit semantics across ancestry + local branch history.
- Query participant/relationship-reference indexes, not payload JSON or current State inference.
- Ensure no child query sees ancestor Events beyond fork boundary or sibling history.

## Forbidden shortcuts
No second mutable history ledger, current-State reconstruction of trajectory or unbounded public query.

## Acceptance checklist
- [ ] Entity/Relationship trajectories return exact visible Events;
- [ ] parent/child/grandchild boundaries are correct;
- [ ] cursor/limit behavior is deterministic;
- [ ] PostgreSQL indexes/query paths are covered;
- [ ] InMemory/PostgreSQL parity passes;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after ancestry history and scope persistence.
