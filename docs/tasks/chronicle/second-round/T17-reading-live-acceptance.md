---
task: C2-R2-T17
issue: 586
kind: leaf
parent: C2-R2
depends_on: [C2-R2-T16, C2-R2-D01]
created_at: 2026-09-08
---

# 真实章节阅读、事件定位与第二轮独立验收

## Scope

[Issue #586](https://github.com/6spot/Loom/issues/586) owns the bounded implementation steps. 在全新数据环境中用真实 provider 和固定完整章节验证第二轮可读性、叙事时间、事件对应和返回体验，独立结束本轮。

Canonical contracts: [continuous reading](../../../../apps/chronicle/docs/continuous-reading.md), [reading experience](../../../../apps/chronicle/docs/reading-experience.md). Dependency and file ownership: [initiative index](README.md).

## Acceptance

- [ ] 四个完整自然章通过真实0.2生产/审核/发布，译文及来源可完整阅读。
- [ ] 至少12个真实核对点证明时间、回溯、事件和人物地点对应；未知保留，未来头衔不被带入。
- [ ] 事件/其他来源/原文探索能返回原 unit 与叙事时间，桌面与窄屏流程有实际证据。
- [ ] 所有自动门与独立内容审核通过，未验证项如实记录且不能被当成已验收。
- [ ] 本轮所有子任务满足各自验收要求，相关 CI 与独立内容核对证据完整。

## Verification requirements

Run the checks specified in the linked Issue and the current [delivery guide](../../../development/task-completion.md). Record actual acceptance, test/CI results and any unavailable checks in the delivery PR.

## Progress Log

- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
- 2026-09-08 — Final gate also waits for design-preparation D01/#588. D01 delivers the reusable background skill and candidate archive only; future Studio/image-display tasks are not silently added to this acceptance scope.
