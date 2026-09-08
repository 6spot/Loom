---
task: C2-R2-T15
issue: 584
kind: leaf
parent: C2-R2
status: planned
depends_on: [C2-R2-T06, C2-R2-T09, C2-R2-T10, C2-R2-T11, C2-R2-T12, C2-R2-T13, C2-R2-T14]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 统一接入连续阅读页面、事件入口与生产构建

## Scope

[Issue #584](https://github.com/6spot/Loom/issues/584) owns the bounded implementation steps. 把并行完成的模块接成真实公开阅读页面，使篇章/Timeline/Event/Entity 的探索和返回成为完整用户流程。

Canonical contracts: [continuous reading](../../../../apps/chronicle/docs/continuous-reading.md), [reading experience](../../../../apps/chronicle/docs/reading-experience.md). Dependency and file ownership: [initiative index](README.md).

## Acceptance

- [ ] 可从公开目录/章/事件进入真实连续正文，逐段推进时轴与人物地点一致。
- [ ] 事件预览→发生位置/其他来源→详情→返回恢复准确位置和叙事时间。
- [ ] unknown、回溯和 source 时间不被全局时间栏改写；刷新/直接深链接可用。
- [ ] 桌面/平板/窄屏正文优先，无技术字段占据默认流程；原页与 Studio 保持可操作。
- [ ] 生产构建与提交 dist/Rust 资源一致，真实 Rust 入口能服务新页面。

## Verification

Not run. Implementation has not started. During delivery record actual test/CI evidence and any unavailable checks. Cross-round governance includes the first-round and second-round records as described in [task-completion](../../../development/task-completion.md#dependencies-across-initiative-directories).

## Progress Log

- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
