---
task: C1-T8
issue: 497
status: planned
depends_on: [C1-T7]
created_at: 2026-09-04
started_at:
completed_at:
completion_pr:
merge_sha:
---

# Chronicle Review, Resolution and Canonical Publication

## Canonical scope

GitHub Issue #497 is the executable specification.

## Goal

Integrate new source bundles with existing conservative cross-source resolution, durable ReviewItems, and canonical publication without weakening C0 identity semantics.

## Acceptance

- [ ] new source bundles resolve against the persisted corpus through C0 semantics.
- [ ] ambiguous decisions remain explicit and reviewable.
- [ ] review decisions are durable and deterministic on resume.
- [ ] stable canonical identities are reused/attached correctly.
- [ ] uncertain/not-same/related-occurrence boundaries remain preserved.
- [ ] publication conflicts fail closed.
- [ ] job outputs link exact bundle/resolution/catalog artifacts.
- [ ] C0 real-data publication regressions remain green.
- [ ] PostgreSQL 18/Chronicle CI passes.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
