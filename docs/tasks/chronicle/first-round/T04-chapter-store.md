---
task: C2-R1-T04
issue: 554
kind: leaf
parent: C2-R1
status: planned
depends_on: [C2-R1-T01]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 章产物存储、租约写入与发布记录表

## Scope

[Issue #554](https://github.com/6spot/Loom/issues/554) owns this bounded implementation checklist. 完整译文、提取结果和引用一起接受，恢复时不会拿半份或另一个版本的结果继续。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). File ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] fresh PG18 迁移、重复执行迁移、完整产物写读成功。
- [ ] 半产物、错revision/producing-run/lease、hash冲突、重复pub不幂等问题均有负例。
- [ ] 0.1或错误scope不能同bundle；0.2受控写入可用；自反 Entity/Event link 拒绝。
- [ ] 未调用 publication helper前公共目录不可见；原 Reader Presentation Claim约束未放宽。

## Verification

Not run. Implementation has not started; commands and required scenarios are recorded in the linked Issue. Record actual commit/CI/test results here during delivery, including any unverified checks and reasons.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
