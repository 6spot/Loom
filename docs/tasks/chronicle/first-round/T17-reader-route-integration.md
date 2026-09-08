---
task: C2-R1-T17
issue: 567
kind: leaf
parent: C2-R1
status: planned
depends_on: [C2-R1-T12, C2-R1-T14, C2-R1-T15, C2-R1-T16]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 篇章阅读接入公开导航、Rust路由与构建资源

## Scope

[Issue #567](https://github.com/6spot/Loom/issues/567) owns the bounded implementation checklist. 用户从现有公开导航就能进入完整白话篇章，直接打开和刷新也可用，浏览器实际走生产Rust front。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 从公开导航完成目录→完整章→引用→整章原文→返回正文，首尾无缺失。
- [ ] 直接打开/刷新chapters路径成功，全部静态资源由Rust正确返回。
- [ ] 未发布章节public404，Studio仍需认证；API错误保留JSON状态码。
- [ ] 生产build与提交dist一致，现有审核连审及事件/人物页面回归通过。

## Verification

Not run. Implementation has not started; commands and required scenarios are in the linked Issue. Record actual commit/CI/test results here during delivery, including any unverified checks and reasons.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
