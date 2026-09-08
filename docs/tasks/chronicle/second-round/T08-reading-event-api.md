---
task: C2-R2-T08
issue: 577
kind: leaf
parent: C2-R2
status: planned
depends_on: [C2-R2-T04, C2-R2-T05]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 固定快照的事件预览与跨来源正文位置反查

## Scope

[Issue #577](https://github.com/6spot/Loom/issues/577) owns the bounded implementation steps. 按确认的 canonical Event 提供轻量预览、发生段落和提及位置；既有 Event/Entity 详情支持同一可选快照，保持探索范围一致。

Canonical contracts: [continuous reading](../../../../apps/chronicle/docs/continuous-reading.md), [reading experience](../../../../apps/chronicle/docs/reading-experience.md). Dependency and file ownership: [initiative index](README.md).

## Acceptance

- [ ] 同名不同 ID 不串线；只有 current 位置可作为发生段落，retrospective 不被当默认定位。
- [ ] 不同来源的同 canonical Event 都能分页看到，首批不冒充全部。
- [ ] 预览的时间/文本/来源都属于选定快照，后来发布的成员不会渗入旧卡片。
- [ ] 没有摘要/发生段落时保持可用状态且不调用模型、不写 DB。
- [ ] 携带 catalog 的既有 Event/Entity 详情不混入后续成员/关系；不传 catalog 的原有 API 回归通过。

## Verification

Not run. Implementation has not started. During delivery record actual test/CI evidence and any unavailable checks. Cross-round governance includes the first-round and second-round records as described in [task-completion](../../../development/task-completion.md#dependencies-across-initiative-directories).

## Progress Log

- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
