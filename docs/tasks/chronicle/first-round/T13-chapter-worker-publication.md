---
task: C2-R1-T13
issue: 563
kind: leaf
parent: C2-R1
status: in_progress
depends_on: [C2-R1-T03, C2-R1-T04, C2-R1-T05, C2-R1-T06, C2-R1-T07, C2-R1-T08]
created_at: 2026-09-08
started_at: 2026-09-09
completed_at:
completion_pr:
merge_sha:
---

# 唯一worker接线、章级恢复与原子公开发布

## Scope

[Issue #563](https://github.com/6spot/Loom/issues/563) owns the bounded implementation checklist. 把已独立验证的模块接到真实导入链，整章完整产物可重启恢复，catalog与可读译文同一次提交公开。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 从新revision走通完整章extract→assemble→human review→publish；无candidate可直接发布。
- [ ] kill/takeover、慢模型、取消、过期lease、accepted-run收养都不重复接受或丢产物。
- [ ] 任一章缺失/无效、仍open review或错frozen plan都不能出现部分公开catalog/译文。
- [ ] 两个publisher等待顺序不会被imported_at误判；基线变化产生新候选时fail closed。
- [ ] 所有publications绑定原artifact/revision；同revision变内容拒绝；没有把简介当全文的旧生产支路。

## Verification

Implemented and verified against local PostgreSQL 18 + pgvector
(`tools/postgres-test.sh` service, isolated databases per test):

- `worker/test_chapter_pipeline_postgres.py` (new, 12 tests): full
  extract→assemble→review→publish→present, review-gated resume,
  accepted-run adoption with zero model calls, takeover without
  writes, moved-baseline `publication_plan_stale` with no public
  content, sequence-ordered second publisher, same-revision
  `immutable_artifact_conflict`, chapter-model-without-source and
  source-without-model fail-closed before any branching,
  expired-lease publish fence, exact T05 header envelope, required
  per-chapter assembly content hash, and direct real-fixture T05
  answers (no test adapter). All pass.
- `worker/test_*postgres.py` (incl. the new file and the updated
  source fail-closed test), worker unit (incl. chapter entry and
  fixture envelope), persistence unit and postgres, read_api
  postgres (incl. coverage): all pass.
- Review rounds (CHANGES_REQUIRED → addressed): `chapter_plan.py`
  reverted — the chapter-slice hash rebinding lives in the T13-owned
  wiring layer; `assembly.py` keeps the minimal per-chapter content
  binding the review requires (synthetic T07 fixtures aligned);
  the T05/T06 envelope is unified in `fixture_model.py` (legacy
  envelope preserved, all T06 unit tests green); the legacy
  `postgres_v0` catalog writer now uses the shared lock.
- Ownership coordination: T07-side `assembly.py` /
  `test_assembly_unit.py` changes cannot be moved into T13 files
  (the old triple check rejects every real multi-chapter artifact)
  nor reverted without breaking acceptance; explicit owner review
  requested at
  https://github.com/6spot/Loom/issues/557#issuecomment-5595488741
  (minimal hunk, C1 path untouched, revert/adopt notes included).

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-09 — Implementation in progress: sole wiring in
  `ingestion_worker.py` via new `worker/chapter_stage.py`; atomic
  `resolve_publish.publish_chapters` under the unified advisory lock
  with `publication_sequence` latest-catalog reads (`coverage.py`
  aligned, legacy publish writes locked); production chapter entry
  in `production_worker.py`; docs updated in `worker.md`.
- 2026-09-09 — Review findings addressed on PR #609: ownership
  restored (T03 revert, T07 change minimized + flagged),
  missing-model fail-closed at job start, exact envelope parsing,
  mandatory content-hash validation, expiry-aware publish fence
  with regression tests, remaining catalog writer locked.
- 2026-09-09 — Second review round on PR #609: T07 coordination
  requested explicitly on issue #557 with revert/adopt notes;
  T05/T06 envelope unified in the fixture (legacy path preserved,
  test-only adapter deleted, real-fixture coverage added);
  source-without-chapter-model now rejected at job start before any
  legacy/fake branching (C1 fail-closed test updated to the new
  expectation).
- 2026-09-09 — Third review round on PR #609: fail-closed moved to
  the production entry (`require_production_entry` refuses a sourced
  worker without models before claiming; library composability for
  explicit injection preserved with the pinned C1 tests green);
  fixture accepts both the legacy and the production T05 envelopes
  (T06 unit tests green, adapter deleted); T07 coordination recorded
  at
  https://github.com/6spot/Loom/issues/557#issuecomment-5595488741.
