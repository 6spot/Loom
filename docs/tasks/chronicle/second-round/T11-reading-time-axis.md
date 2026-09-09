---
task: C2-R2-T11
issue: 580
kind: leaf
parent: C2-R2
depends_on: [C2-R2-T01, C2-R2-T02]
created_at: 2026-09-08
---

# 按叙事时间分组的侧边轴与窄屏时间入口

## Scope

[Issue #580](https://github.com/6spot/Loom/issues/580) owns the bounded implementation steps. 以低干扰侧边时间轴定位阅读区段，同年月共享标记，保持原始历法、未知和倒叙的含义。

Canonical contracts: [continuous reading](../../../../apps/chronicle/docs/continuous-reading.md), [reading experience](../../../../apps/chronicle/docs/reading-experience.md). Dependency and file ownership: [initiative index](README.md).

## Acceptance

- [ ] 同月跨页只一个年/月语义区段；换月/年层级正确，未知不继承上次日期。
- [ ] 传统八月不会显示为公历八月；源/公历、近似和分歧标签不混淆。
- [ ] 倒叙与跨章保留阅读顺序；点击发送准确 locator，不只传 year。
- [ ] 窄屏轴不挤正文，键盘能选择区段/关闭/恢复焦点。

## Verification requirements

Run the checks specified in the linked Issue and the current [delivery guide](../../../development/task-completion.md). Record actual acceptance, test/CI results and any unavailable checks in the delivery PR.

## Progress Log

- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
