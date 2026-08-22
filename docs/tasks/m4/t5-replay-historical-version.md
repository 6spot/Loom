---
task: M4-T5
issue: 65
status: planned
depends_on: [62, 63, 64]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M4-T5 — Replay Arbitrary Committed TimelineVersion

## Goal

Reconstruct exact World materialization plus logical unresolved future at any committed Timeline version.

## Required implementation

- Add Runtime historical reconstruction over ordered committed Events plus logical Work transitions.
- Return exact structural/Facet/Relationship State, World Time/head position and logical Pending Work at the requested version.
- Define version-zero/initial semantics and typed errors for nonexistent/gapped/inconsistent versions.
- Provide InMemory and PostgreSQL read-path parity; technical Work claim/retry state is not reconstructed as semantic future.

## Forbidden shortcuts

- Do not reverse-diff from today's materialized State.
- Do not query today's Work table as historical Pending Work.
- Do not rerun current Capability code or expose public fork here.

## Acceptance checklist

- [ ] initial, intermediate and current versions reconstruct exactly;
- [ ] Work schedule/cancel/complete intervals reconstruct correctly;
- [ ] invalid/gapped versions fail deterministically;
- [ ] PostgreSQL reconstruction survives Runtime/process reconstruction;
- [ ] InMemory/PostgreSQL parity passes;
- [ ] architecture/fmt/check/clippy/tests/rustdoc + PostgreSQL integration pass.

## Completion evidence

- PR:
- merge SHA:
- verification:

## Progress log

- 2026-08-22 — Planned after replay engine, logical transitions and PostgreSQL journal.
