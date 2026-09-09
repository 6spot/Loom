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

- `worker/test_chapter_pipeline_postgres.py` (new, 7 tests): full
  extract→assemble→review→publish→present, review-gated resume,
  accepted-run adoption with zero model calls, takeover without
  writes, moved-baseline `publication_plan_stale` with no public
  content, sequence-ordered second publisher, same-revision
  `immutable_artifact_conflict`. All pass.
- `worker/test_*postgres.py` (53 incl. the new 7), worker unit (94
  incl. chapter entry), persistence unit (338) and postgres (56),
  read_api postgres (53 incl. coverage): all pass.
- Cross-task fixes required for wiring (reported for T03/T07
  owners): `build_chapter_request` binds the chapter slice hash
  (T01 identity check), assembly checks per-chapter content binding;
  test-local adapter bridges the T05 prompt / T06 fixture
  `CHAPTER_REQUEST` envelope drift.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-09 — Implementation in progress: sole wiring in
  `ingestion_worker.py` via new `worker/chapter_stage.py`; atomic
  `resolve_publish.publish_chapters` under the unified advisory lock
  with `publication_sequence` latest-catalog reads (`coverage.py`
  aligned, legacy publish writes locked); production chapter entry
  in `production_worker.py`; docs updated in `worker.md`.
