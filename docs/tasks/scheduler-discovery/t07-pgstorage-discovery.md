---
task: SCHD-T07
issue: 409
status: planned
depends_on: [405, 408]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T07 — Implement PgStorage Scheduler discovery adapter

## Goal

Wire the T06 SQL into `PgStorage` as the T03 persistence implementation.

## Scope and acceptance

- [ ] Load repository SQL through the existing `include_str!` ownership pattern
      and implement the T03 trait.
- [ ] Bind bound/cursor values once, decode typed target IDs with existing
      helpers, and preserve SQL order/continuation.
- [ ] Map SQL/decoding failures to the typed storage error without exposing
      SQLx/PostgreSQL types above `loom-storage`.
- [ ] Keep the operation read-only and avoid schema/index or claim changes.
- [ ] Focused success, empty-result and error-mapping tests plus standard
      storage checks pass.
