---
task: C2-R1-T08
issue: 558
kind: leaf
parent: C2-R1
status: in_progress
depends_on: [C2-R1-T04, C2-R1-T07]
created_at: 2026-09-08
started_at: 2026-09-09
completed_at:
completion_pr:
merge_sha:
---

# 同书跨章候选、混合审核计划与发布器版本适配

## Scope

[Issue #558](https://github.com/6spot/Loom/issues/558) owns the bounded implementation checklist. 同一revision的不同章也能有依据地审核身份；全部决定进入同一最终图，避免书内same-link只停留在assembly报告中。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 同书A/B两章曹操候选能审核并由原union规则发布为同一identity；同名无充分依据仍可uncertain。
- [ ] 一个job混合chapter_pair和published_batch，全部candidate恰好覆盖一次；错mode/组/重复或漏候选拒绝。
- [ ] 跨章same链桥接两个已发布ID时拒绝；not_same/related/uncertain不误合并。
- [ ] 同plan恢复不重复债务；0.2来源hash与canonical event relation provenance一致。

## Verification

2026-09-09 — Implementation on branch `agent/executor/c8ce89c3b323` (delivery PR pending; no completion claim):

- `python3 -m unittest discover -s apps/chronicle/persistence -p 'test_resolve_publish_unit.py' -v` — **33 tests OK** (was 24; +9 chapter-path tests: within-bundle blocking/uncertainty, mixed plan exact-once coverage, mode/group/duplicate rejection, fingerprint stability + tamper evidence, union merge vs uncertain-distinct, downgrade refusal, self-link ban).
- `python3 -m unittest discover -s apps/chronicle/persistence -p 'test_*review*_unit.py' -v` — **35 tests OK** (was 24; +11 new `test_review_subjects_chapter_unit.py`: per-candidate pair subjects, pair-only fan-out, mixed coexistence, legacy-mix rejection, bridge rejection via `canonical_identity_conflict`, not_same bridge break).
- `python3 -m unittest discover -s apps/chronicle/ingestion/prototype -p 'test_resolution_v0.py' -v` — **7 tests OK**; `-p 'test_publication_v0.py'` — **11 tests OK** (legacy envelopes unchanged).
- `python3 -m unittest discover -s apps/chronicle/persistence -p 'test_chapter_store_postgres.py'` — **17 tests OK** (regression: 0006 envelope + Reader constraint untouched).
- Live PG18 scope check (isolated database, migrations applied): `0.2`/`within_revision` persists with scope stored, legacy `0.1` cross-source persists with NULL scope, `0.1` same-bundle rejected — **passed**.
- `git diff --check` — **clean**.
- Dependency reconciliation: C2-R1-T04 ledger is `in_progress` and C2-R1-T07 ledger is `planned` on the default branch (`main` contains neither merge); both code merges exist only on the stacked branch. Per the Issue, this task **cannot close** until T04/T07 reconcile to `completed` on the default branch. No UI change, so no test/build/smoke:dist applies. No new migration; `ingestion_worker.py` untouched.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-09 — Implementation started per Leader dispatch on `agent/executor/c8ce89c3b323`. Dependency note: C2-R1-T04/T07 code is present on the stacked branch but neither Task Ledger is `completed` on the default branch, so close-out remains blocked on their reconciliation; this task consumes only their contract code, not their completion status.
