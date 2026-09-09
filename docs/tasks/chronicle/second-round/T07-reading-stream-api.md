---
task: C2-R2-T07
issue: 576
kind: leaf
parent: C2-R2
depends_on: [C2-R2-T04, C2-R2-T05]
created_at: 2026-09-08
---

# 连续正文分页、侧轴区段与精确 locate 查询

## Scope

[Issue #576](https://github.com/6spot/Loom/issues/576) owns the bounded implementation steps. 实现 stream 目录/详情、双向正文页、分组页和精确 unit 定位的 SELECT-only 领域查询，为前端提供固定快照与稳定坐标。

Canonical contracts: [continuous reading](../../../../apps/chronicle/docs/continuous-reading.md), [reading experience](../../../../apps/chronicle/docs/reading-experience.md). Dependency and file ownership: [initiative index](README.md).

## Acceptance

- [ ] 双向遍历无遗漏/重复，全部文本按源顺序可到达，页大小限制不截断 unit。
- [ ] 第 4,900 个 synthetic unit 可直接 locate，不读取前 4,899 个正文。
- [ ] 同 group 跨页 ID/continuation 一致；换 scope/snapshot/方向的 cursor 拒绝。
- [ ] 旧快照不漂移，未知/未发布/跨 stream unit 不可见，GET 无写入。

## Verification requirements

Run the checks specified in the linked Issue and the current [delivery guide](../../../development/task-completion.md). Record actual acceptance, test/CI results and any unavailable checks in the delivery PR.

## Progress Log

- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
