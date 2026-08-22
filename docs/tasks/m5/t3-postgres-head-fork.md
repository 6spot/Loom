---
task: M5-T3
issue: 70
status: planned
depends_on: [68, 69]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M5-T3 — PostgreSQL Atomic Head Fork

## Goal
Implement current-head fork as one PostgreSQL authority transaction with InMemory parity.

## Required implementation
- Add additive ancestry/EventRef persistence migrations required by #68.
- Runtime-owned fork port implemented by `loom-storage`.
- One transaction validates source head, inserts child Timeline, copies materialized structure/facets/relationships, clones Pending Work with new IDs/reset technical state and records ancestry.
- Do not duplicate ancestor Event ledger rows.
- Preserve source under every rollback/failure path.

## Forbidden shortcuts
No table-by-table autocommit, copied retry metadata, copied Event rows or migration rewrites.

## Acceptance checklist
- [ ] fresh PostgreSQL 18 migrations pass;
- [ ] head fork is atomic/rollback-safe;
- [ ] child State/Future matches source head;
- [ ] cloned Work IDs differ/reset correctly;
- [ ] restart and InMemory/PostgreSQL parity pass;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after #69.
