---
task: M10-T4
issue: 108
status: planned
depends_on: [105, 106, 107]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M10-T4 — Atomic Template Bootstrap

## Goal
Birth a Template-backed World atomically with semantic initial State produced only through normal Resolution/Event semantics.

## Required implementation
- Add Runtime-owned bootstrap persistence authority implemented by storage.
- Allocate identities and resolve ordered bootstrap Actions against ephemeral empty candidate/exact enabled capabilities.
- Aggregate owner-tagged segments; validate schemas/ownership/invariants/budgets/reactions before persistence.
- One transaction persists World, Timeline, bindings, initial Event ledger/materialized State/logical Work/reaction Work/logical commit history.
- Rejection/validation/persistence failure leaves no birth artifact; resulting Events replay exactly.

## Forbidden shortcuts
No create-empty-then-many-transactions bootstrap, direct SQL Facet/Entity semantic inserts, partial World or Runtime→PgStorage dependency.

## Acceptance checklist
- [ ] success creates exact World/history/state/work/bindings;
- [ ] all failure classes leave no World artifacts;
- [ ] bootstrap Events replay to initial State;
- [ ] reaction initial Work is atomic;
- [ ] version/time/EventSeq semantics pass;
- [ ] adapter/PostgreSQL parity passes.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after Template assembly.
