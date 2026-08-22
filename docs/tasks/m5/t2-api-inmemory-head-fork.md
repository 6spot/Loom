---
task: M5-T2
issue: 69
status: planned
depends_on: [68]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M5-T2 — Public Fork API + InMemory Head Fork

## Goal
Expose focused `loom-api` fork contracts and implement current-head fork on InMemory authority.

## Required implementation
- Add transport-neutral fork request/result/ancestry DTOs to Timeline service.
- Runtime allocates child TimelineId and validates World/Timeline target.
- Clone current materialized State and logical Pending Work, preserving existing Entity/Relationship IDs.
- Allocate new WorkIds and reset technical claim/lease/fence/attempt/error state.
- Persist immutable ancestry and allow independent child commits.

## Forbidden shortcuts
No copied ancestor Event rows, Runtime-specific public API, reused WorkIds or historical fork yet.

## Acceptance checklist
- [ ] public API is architecture-safe;
- [ ] child State/Future equals source head at birth;
- [ ] source remains unchanged and child commits independently;
- [ ] Work identity/reset semantics pass;
- [ ] invalid target fails deterministically;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after #68.
