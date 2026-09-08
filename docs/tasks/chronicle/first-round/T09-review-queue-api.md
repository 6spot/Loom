---
task: C2-R1-T09
issue: 559
kind: leaf
parent: C2-R1
status: planned
depends_on: []
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 审核队列范围、稳定分页及全部页消费者

## Scope

[Issue #559](https://github.com/6spot/Loom/issues/559) owns the bounded implementation checklist. 消除首200项限制和offset分页漏审，为连续审核提供真实范围、稳定游标和待审计数。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 450项以上、相同created_at、多job和kind的筛选/翻页/计数正确。
- [ ] 处理前页后继续游标不会漏中间项；旧cursor不能套到别的scope。
- [ ] 晚提交落在旧cursor前的项能在从头重读时发现；API不谎称冻结总数。
- [ ] 现页面和验收脚本仍可工作，没有首200项作为全量结论的残留消费者。

## Verification

Not run. Implementation has not started; commands and required scenarios are in the linked Issue. Record actual commit/CI/test results here during delivery, including any unverified checks and reasons.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
