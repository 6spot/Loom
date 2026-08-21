---
task: M2-T1
issue: 26
status: planned
depends_on: []
created_at: 2026-08-21
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M2-T1 — PostgreSQL Schema and SQLx Migration Foundation

## Goal

Introduce the PostgreSQL 18 + SQLx storage foundation and freeze a human-readable v0 schema that faithfully persists the Runtime contracts proven in Milestone 1.

## Scope

- SQLx PostgreSQL/migration support stays in `loom-storage` or permitted test/application infrastructure.
- Add the `PgStorage` construction boundary without leaking SQLx/PgPool into higher contract crates.
- Check human-readable SQLx migration SQL into the repository.
- Persist World/Timeline identity and TimelineVersion, Event ledger/order and references, current Entity/Relationship/Facet state, and Durable Work/runtime metadata required by existing Runtime persistence ports.
- Preserve World Time vs Platform Time separation and real relational integrity.
- Do not introduce an ORM abstraction that obscures CAS/locking behavior.

## Acceptance checklist

- [ ] migrations apply to an empty PostgreSQL 18 database;
- [ ] migration setup/replay is deterministic in tests;
- [ ] basic `PgStorage` connect/health path works;
- [ ] representative schema constraints reject invalid duplicate/foreign-key identities;
- [ ] no forbidden Cargo dependency edge is introduced;
- [ ] architecture, fmt, check, clippy, tests and rustdoc pass.

## Completion evidence

- PR:
- merge SHA:
- CI / verification:
- notes:

## Progress log

- 2026-08-21 — Task record created from issue #26; status `planned`.
