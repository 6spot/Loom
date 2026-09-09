---
task: C2-R2-T13
issue: 582
kind: leaf
parent: C2-R2
depends_on: [C2-R2-T01, C2-R2-T02]
created_at: 2026-09-08
---

# 正文事件词预览、触屏入口与目标选择组件

## Scope

[Issue #582](https://github.com/6spot/Loom/issues/582) owns the bounded implementation steps. 让已确认事件词支持轻量预览、查看详情、定位发生位置和其他记载选择，保持阅读状态及可访问性。

Canonical contracts: [continuous reading](../../../../apps/chronicle/docs/continuous-reading.md), [reading experience](../../../../apps/chronicle/docs/reading-experience.md). Dependency and file ownership: [initiative index](README.md).

## Acceptance

- [ ] 事件词位置来自结构化 segments，未做全局字符串 replace/innerHTML/名称查找。
- [ ] hover、键盘和触屏均可完成预览/选择/关闭；进入卡片不闪退、Esc 回触发词。
- [ ] 多目标要选择，回溯-only 不成为发生位置；同名未确认事件不静默跳错。
- [ ] 不为全文全部事件预取，缓存快照隔离，旧响应不覆盖新预览或改变阅读时间。

## Verification requirements

Run the checks specified in the linked Issue and the current [delivery guide](../../../development/task-completion.md). Record actual acceptance, test/CI results and any unavailable checks in the delivery PR.

## Progress Log

- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
