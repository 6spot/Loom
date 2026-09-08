---
task: C2-R1-T15
issue: 565
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

# 完整白话阅读、篇章目录与按需引用组件

## Scope

[Issue #565](https://github.com/6spot/Loom/issues/565) owns the bounded implementation checklist. 用真实组件呈现单栏完整白话和按需原文，独立于现有审核页与共享路由先完成。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 长章末段可达，默认无逐句双栏，来源按需展开不丢阅读位置。
- [ ] 多引用/长章分页、错误重试、快速切换两publication不会串旧响应。
- [ ] 键盘与移动尺寸可用，来源恶意HTML不执行，无摘要冒充全文。
- [ ] 组件harness有真实交互证据；未挂接模块构建不改变生产dist。

## Verification

Not run. Implementation has not started; commands and required scenarios are in the linked Issue. Record actual commit/CI/test results here during delivery, including any unverified checks and reasons.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
