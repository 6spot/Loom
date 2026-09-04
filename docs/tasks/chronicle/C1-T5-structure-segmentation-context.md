---
task: C1-T5
issue: 494
status: in_progress
depends_on: [C1-T3, C1-T4]
created_at: 2026-09-04
started_at: 2026-09-04
completed_at:
completion_pr:
merge_sha:
---

# Chronicle Structure, Segmentation and Context State

## Canonical scope

GitHub Issue #494 is the executable specification.

## Goal

Produce reproducible document sections and semantic chunks within model budgets while forwarding bounded contextual state across chunk boundaries.

## Acceptance

- [ ] section/chunk records retain exact source locators.
- [ ] unchanged input/version produces reproducible segmentation.
- [ ] model context budgets reserve prompt/context/output safely.
- [ ] natural structure/semantic boundaries are preferred to blind fixed-size cuts.
- [ ] ContextState flows audibly from chunk N to N+1.
- [ ] inherited time/coreference boundary cases are covered without fabricated precision.
- [ ] chunks remain non-authoritative processing units.
- [ ] restart resumes from persisted segmentation checkpoints.
- [ ] Chronicle CI passes.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-04 — Implementation started: versioned structure/segmentation/context module (`persistence/segmentation.py`), worker real `structure`/`segment` path (opt-in, fake path default), per-chunk checkpoint setter, continuity fixture, unit + PostgreSQL resume suites.
- 2026-09-04 — Delivery PR #515 opened (unmerged). Local evidence: 67 persistence tests OK (28 new), 21 worker tests OK (17 C1-T4 unchanged + 4 new). Post-merge reconciliation (completed/completion_pr/merge_sha) pending.
- 2026-09-04 — Reviewer FAIL D-1..D-6 addressed on PR #515: budget total now holds all reserves (D-1); deep-copy merge + repeated-entity regression (D-2); migration 0004 persists section kind/depth/parent with resume validation (D-3); exact persisted-set checks against stale rows (D-5); revision source_sha stored/verified separately from slice hash (D-6); production revision loader wired through --source-dir/CHRONICLE_SOURCE_DIR, run_forever, and the Compose worker volume, all fail-closed (D-4). Local evidence: 71 persistence + 31 worker tests OK; compose config validates.
