---
task: C1-T7
issue: 496
status: in_progress
depends_on: [C1-T6]
created_at: 2026-09-04
started_at: 2026-09-04
completed_at:
completion_pr:
merge_sha:
---

# Chronicle Source Assembly and Within-Book Resolution

## Canonical scope

GitHub Issue #496 is the executable specification.

## Goal

Assemble many validated chunk outputs into one C0-compatible source bundle while conservatively resolving cross-chunk duplication and preserving ambiguity.

## Acceptance

- [ ] one coherent source bundle is produced from many chunk outputs.
- [ ] source/evidence/chunk/run provenance remains traceable.
- [ ] repeated cross-chunk identities/occurrences can be conservatively linked without canonical assignment.
- [ ] boundary-induced duplicate extraction is detected/controlled.
- [ ] ambiguous cases remain distinct/reviewable.
- [ ] unchanged accepted inputs produce deterministic assembly output/report.
- [ ] C0 bundle/schema/evaluator compatibility remains green.
- [ ] Chronicle CI passes.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-04 — Implementation active: pure `persistence/assembly.py` (deterministic revision-scoped merge, boundary-duplicate suppression, conservative within-book links, provenance report) plus real `assemble` worker stage, unit + PostgreSQL tests, `docs/assembly.md`.
