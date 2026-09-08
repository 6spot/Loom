---
task: C2-R1-T18
issue: 568
kind: leaf
parent: C2-R1
status: planned
depends_on: [C2-R1-T17]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 离线全链验收脚本、故障场景与CI接入

## Scope

[Issue #568](https://github.com/6spot/Loom/issues/568) owns the bounded implementation checklist. 在真实产品接口上一次验证本轮完整闭环及失败行为，提供下一任务可直接运行的真实模型验收入口。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 新空PG18/Compose经真实API和浏览器走通第一轮，所有列举故障得到期望结果。
- [ ] fixture结果明确非live，live拒绝fixture/非交互自动决定，脚本不直写DB。
- [ ] 失败和成功证据分开保留，有源码候选SHA和完整来源/产物定位。
- [ ] 新验收guide命令可直接执行，CI paths命中并实际运行离线gate；C1历史记录未改写。

## Verification

Not run. Implementation has not started; commands and required scenarios are in the linked Issue. Record actual commit/CI/test results here during delivery, including any unverified checks and reasons.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
