---
task: M5-T4
issue: 71
status: planned
depends_on: [65, 68, 70]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M5-T4 — Historical Fork from TimelineVersion

## Goal
Create a child from any valid committed historical TimelineVersion using M4 reconstruction.

## Required implementation
- Extend fork request with optional source version under #68 semantics.
- Reconstruct World State + logical unresolved future at the requested version through M4 ports.
- Atomically persist child ancestry/materialization and clone only Work pending at that point with new IDs/reset technical state.
- Reject nonexistent/beyond-head/invalid versions before creating child artifacts.

## Forbidden shortcuts
No current-State copy-and-undo, current Work table as historical truth, copied Event rows or partial child creation.

## Acceptance checklist
- [ ] initial/early/middle/current-version forks pass;
- [ ] State exactly matches source fork point;
- [ ] only historically Pending Work is cloned;
- [ ] later parent changes do not affect child;
- [ ] invalid versions leave no artifacts;
- [ ] InMemory/PostgreSQL/restart parity passes.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after M4 historical replay and M5 head fork.
