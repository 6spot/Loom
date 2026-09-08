---
task: C2-R2-T06
issue: 575
kind: leaf
parent: C2-R2
status: planned
depends_on: [C2-R2-T03, C2-R2-T04, C2-R2-T05]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 把阅读索引接入唯一 worker 和原子发布事务

## Scope

[Issue #575](https://github.com/6spot/Loom/issues/575) owns the bounded implementation steps. 让新环境的生产链在同一次发布中公开 catalog、完整章和阅读索引，失败/接管不会出现半份阅读内容。

Canonical contracts: [continuous reading](../../../../apps/chronicle/docs/continuous-reading.md), [reading experience](../../../../apps/chronicle/docs/reading-experience.md). Dependency and file ownership: [initiative index](README.md).

## Acceptance

- [ ] 正常链路公开完整章和阅读 stream；一份 revision 只有一个 stream。
- [ ] 任意发布中断/过期 lease 不泄漏部分 catalog/章节/阅读索引。
- [ ] 接管/重试幂等且不为阅读再调用模型或重建人审计划。
- [ ] source/plan/config/annotation 漂移与混版本被拒绝，既有 canonical 语义未改变。

## Verification

Not run. Implementation has not started. During delivery record actual test/CI evidence and any unavailable checks. Cross-round governance includes the first-round and second-round records as described in [task-completion](../../../development/task-completion.md#dependencies-across-initiative-directories).

## Progress Log

- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
