---
task: M11-T2
issue: 114
status: planned
depends_on: [113]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M11-T2 — Runtime Revision Ledger

## Goal
Persist immutable Runtime revisions and active-revision history independently from World Events.

## Required implementation
- Runtime-owned revision persistence/admin port + additive PostgreSQL/InMemory storage.
- Server startup registers/confirms its build/revision/capability implementation refs.
- Explicit concurrency-safe publish/activation under #113; historical rows are immutable.
- Typed behavior for unknown/incompatible revision and server-build/active-revision mismatch.
- Read active revision/history for Admin.

## Forbidden shortcuts
No single mutable version string, activation World Event, secrets in metadata or undocumented auto-activation on process start.

## Acceptance checklist
- [ ] revisions persist/reload immutably;
- [ ] active selection/activation is concurrency-safe/auditable;
- [ ] restart preserves activation history;
- [ ] startup mismatch behavior is deterministic;
- [ ] activation leaves World Event/State unchanged;
- [ ] adapter/migration/architecture gates pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after #113.
