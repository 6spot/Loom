---
task: M10-T5
issue: 109
status: planned
depends_on: [108]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M10-T5 — Bootstrap InMemory/PostgreSQL Parity

## Goal
Harden bootstrap with one reusable authority contract suite, especially rollback/restart behavior.

## Required verification
Cover multi-Action/subresolution success, structural/facet/relationship Effects, Work/Reaction Work, duplicate identity/conflict, invalid input, rejection, resolver/invariant/ownership/budget/persistence failures. Every failure must leave no World/Timeline/binding/Event/State/Work/logical-commit orphan; success must immediately support read/replay/fork/restart.

## Forbidden shortcuts
No weaker adapter criteria, cleanup-after-failure hiding non-atomicity or direct SQL fixture mutation for success assertions.

## Acceptance checklist
- [ ] common suite runs both adapters;
- [ ] failure matrix proves all-or-nothing birth;
- [ ] success survives restart/replay/fork;
- [ ] Template/capability provenance is exact/immutable;
- [ ] architecture/fmt/check/clippy/tests/rustdoc/PostgreSQL pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after atomic bootstrap.
