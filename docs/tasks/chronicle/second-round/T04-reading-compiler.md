---
task: C2-R2-T04
issue: 573
kind: leaf
parent: C2-R2
status: planned
depends_on: [C2-R2-T01, C2-R1-T19]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 阅读注解 remap、时间分组和不可变投影编译

## Scope

[Issue #573](https://github.com/6spot/Loom/issues/573) owns the bounded implementation steps. 复用章到 revision 的唯一映射，将阅读注解编译为单位、时间分组和事件位置索引，完全保留正文顺序与来源。

Canonical contracts: [continuous reading](../../../../apps/chronicle/docs/continuous-reading.md), [reading experience](../../../../apps/chronicle/docs/reading-experience.md). Dependency and file ownership: [initiative index](README.md).

## Acceptance

- [ ] 同一输入编译字节稳定；全部 chapter/block 按源顺序出现且正文完全相等。
- [ ] 跨章重名/重复 local temp refs 经唯一映射后仍正确，未知不会被名称自动绑定。
- [ ] 同月共享标记、换月只换月、未知与 source/Gregorian 不误合并，倒叙不重排。
- [ ] current 与 retrospective 目标区分；无来源支持的角色或断裂继承导致编译拒绝。

## Verification

Not run. Implementation has not started. During delivery record actual test/CI evidence and any unavailable checks. Cross-round governance includes the first-round and second-round records as described in [task-completion](../../../development/task-completion.md#dependencies-across-initiative-directories).

## Progress Log

- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
