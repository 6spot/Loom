---
task: M4-T2
issue: 147
status: planned
depends_on: [146]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M4-T2 — Immutable World Runtime Binding

## Goal

Persist World Runtime Binding as World-level Runtime Metadata and eliminate implicit `installed registry == enabled for this World` behavior.

## Implementation contract

- Runtime owns the binding descriptor/ports; Storage implements persistence.
- Binding stores semantic Capability IDs, compatibility requirements and immutable World config — never resolver objects or permanently pinned exact binaries.
- Binding is shared by all Timelines of one World and immutable in v0.
- Direct Action routing must enforce it immediately; later Work/Reaction/retrieval tasks reuse the same lookup boundary.
- Add additive InMemory/PostgreSQL persistence.
- Migrate M3-era Worlds by an explicit one-time compatibility binding; no live fallback to all currently installed software.

## Forbidden shortcuts

No per-Timeline binding, Template live subscription, exact Session implementation stored as binding, or registry-presence fallback after migration.

## Acceptance

- [ ] Different Worlds can have different bindings under one installed registry.
- [ ] Disabled installed Action is unavailable.
- [ ] Binding survives restart and cannot mutate in v0.
- [ ] Legacy data receives deterministic persisted binding.
- [ ] InMemory/PostgreSQL + standard gates pass.

Architecture basis: `world-runtime.md` Binding; `implementation.md` Binding/Execution Assembly distinction.

## Verification evidence

Pending.

## Progress Log

- 2026-08-22 — Planned.