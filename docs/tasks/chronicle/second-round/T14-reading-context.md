---
task: C2-R2-T14
issue: 583
kind: leaf
parent: C2-R2
status: planned
depends_on: [C2-R2-T01, C2-R2-T02]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 当前正文人物、地点及有来源的事件角色组件

## Scope

[Issue #583](https://github.com/6spot/Loom/issues/583) owns the bounded implementation steps. 随 active unit 展示本段主要人物、地点和政权/其他对象，保留来源和事件角色，避免引入第三轮的长期状态计算。

Canonical contracts: [continuous reading](../../../../apps/chronicle/docs/continuous-reading.md), [reading experience](../../../../apps/chronicle/docs/reading-experience.md). Dependency and file ownership: [initiative index](README.md).

## Acceptance

- [ ] 人物地点随同一个 active unit 更新，回读前段能恢复，不显示最后/全章人物。
- [ ] 同名不同 ID 保持分开，去重不丢来源角色，unknown/空段不自动补全。
- [ ] 事件角色与长期头衔/阵营区分，地点显示不产生人物位置断言。
- [ ] 窄屏入口、查看来源/实体和关闭返回焦点都可操作。

## Verification

Not run. Implementation has not started. During delivery record actual test/CI evidence and any unavailable checks. Cross-round governance includes the first-round and second-round records as described in [task-completion](../../../development/task-completion.md#dependencies-across-initiative-directories).

## Progress Log

- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
