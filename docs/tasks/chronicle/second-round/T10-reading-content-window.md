---
task: C2-R2-T10
issue: 579
kind: leaf
parent: C2-R2
depends_on: [C2-R2-T01, C2-R2-T02, C2-R1-T15]
created_at: 2026-09-08
---

# 连续白话正文窗口与按需原文组件

## Scope

[Issue #579](https://github.com/6spot/Loom/issues/579) owns the bounded implementation steps. 实现以正文为主的连续阅读内容窗口，跨章加载不打散原叙事，复用第一轮原文引用组件。

Canonical contracts: [continuous reading](../../../../apps/chronicle/docs/continuous-reading.md), [reading experience](../../../../apps/chronicle/docs/reading-experience.md). Dependency and file ownership: [initiative index](README.md).

## Acceptance

- [ ] 跨章正文顺序、内容与 source 引用完全一致，没有每段重新摘要或卡片墙。
- [ ] 重复页不重复内容；上方窗口移除不会让当前段明显跳位，焦点/选择/引用单位不会消失。
- [ ] 正常 mounted units <=120，操作中的单位最多额外保留 20 个；正常回收继续自动预取，仅不能安全回收时暂停并提供手动入口，不移除正在操作的 DOM。
- [ ] 引用失败不清正文，关闭回到触发点；320px 宽和 200% 字号可阅读。

## Verification requirements

Run the checks specified in the linked Issue and the current [delivery guide](../../../development/task-completion.md). Record actual acceptance, test/CI results and any unavailable checks in the delivery PR.

## Progress Log

- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
