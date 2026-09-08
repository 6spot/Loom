---
task: C2-R2-T01
issue: 570
kind: leaf
parent: C2-R2
status: planned
depends_on: [C2-R1-T01]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 阅读注解、叙事时间与导航 DTO 契约

## Scope

[Issue #570](https://github.com/6spot/Loom/issues/570) owns the bounded implementation steps. 把第二轮 canonical 设计落实为可复用 schema、纯校验器、TypeScript 类型与最小正反例，给后续并行任务固定接口。

Canonical contracts: [continuous reading](../../../../apps/chronicle/docs/continuous-reading.md), [reading experience](../../../../apps/chronicle/docs/reading-experience.md). Dependency and file ownership: [initiative index](README.md).

## Acceptance

- [ ] 0.2 有效章通过且 0.1 语义未被改写；缺一个 block 注解、未知 ref、继承成环/跨章均拒绝。
- [ ] 第二次重复事件词与扩展汉字定位精确；重叠 span 被拒绝，segments 拼回原译文。
- [ ] 回溯事件不能成为当前时间依据，人物角色不能指向别人的 participant。
- [ ] 所有公开 DTO 与 TS 类型可对应同一组 fixture；不存在 canonical ID/URL 由模型写入的入口。

## Verification

Not run. Implementation has not started. During delivery record actual test/CI evidence and any unavailable checks. Cross-round governance includes the first-round and second-round records as described in [task-completion](../../../development/task-completion.md#dependencies-across-initiative-directories).

## Progress Log

- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
