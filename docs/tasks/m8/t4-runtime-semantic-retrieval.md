---
task: M8-T4
issue: 92
status: planned
depends_on: [90, 91]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M8-T4 — Runtime Semantic Retrieval and ReadSet Tracking

## Goal
Provide bounded semantic retrieval through Runtime host/world-view contracts with provenance-ready read evidence.

## Required implementation
- Extend appropriate Capability read host with semantic query; no raw SQL/vector client.
- Validate index availability/ownership and enforce result/byte/query budgets.
- Record query/index identity, projection revision and returned source refs in ReadSet.
- Provide deterministic InMemory test projection + PostgreSQL parity.
- Typed stale/unavailable projection behavior; replay never queries projections.

## Forbidden shortcuts
No PgPool access in Capability, hidden mutation from semantic results, unbounded retrieval or replay-time vector query.

## Acceptance checklist
- [ ] Capability retrieves only through Runtime host;
- [ ] budgets are enforced;
- [ ] ReadSet evidence is deterministic;
- [ ] stale/unavailable behavior is typed;
- [ ] adapter parity and projection-independent replay pass;
- [ ] architecture/fmt/check/clippy/tests/rustdoc/pgvector pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after pgvector storage.
