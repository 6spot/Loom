---
task: C2-R1-T13
issue: 563
kind: leaf
parent: C2-R1
status: planned
depends_on: [C2-R1-T03, C2-R1-T04, C2-R1-T05, C2-R1-T06, C2-R1-T07, C2-R1-T08]
created_at: 2026-09-08
started_at:
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

Not run. Implementation has not started; commands and required scenarios are in the linked Issue. Record actual commit/CI/test results here during delivery, including any unverified checks and reasons.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
