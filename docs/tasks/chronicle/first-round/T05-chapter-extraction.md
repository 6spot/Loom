---
task: C2-R1-T05
issue: 555
kind: leaf
parent: C2-R1
status: planned
depends_on: [C2-R1-T01, C2-R1-T03]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 完整章联合翻译与提取、完整上下文修正

## Scope

[Issue #555](https://github.com/6spot/Loom/issues/555) owns the bounded implementation checklist. 在同一完整章节上下文中同时得到全文白话和可定位的结构信息，任何一部分失败都不接受。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 完整章传入每一轮调用；章尾信息确实在输入中，不只前200字上下文。
- [ ] 合法整份结果一次接受；缺正文/缺引用/只结构等两轮后整体失败，保留失败记录。
- [ ] 输入/输出超限不截断且不回退chunk；修正次数及运输重试有清楚区别。
- [ ] 同章ref共享、歧义/时间/嵌注合同fixture通过；机械通过不被宣传为内容正确率。

## Verification

Not run. Implementation has not started; commands and required scenarios are in the linked Issue. Record actual commit/CI/test results here during delivery, including any unverified checks and reasons.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
