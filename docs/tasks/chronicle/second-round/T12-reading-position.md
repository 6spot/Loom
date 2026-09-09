---
task: C2-R2-T12
issue: 581
kind: leaf
parent: C2-R2
depends_on: [C2-R2-T01, C2-R2-T02]
created_at: 2026-09-08
---

# 当前片段、深链接、返回栈与滚动恢复控制器

## Scope

[Issue #581](https://github.com/6spot/Loom/issues/581) owns the bounded implementation steps. 统一 active unit 和阅读定位状态，使正文、时间轴、人物地点同步，并能从引用/事件/其他来源可靠返回。

Canonical contracts: [continuous reading](../../../../apps/chronicle/docs/continuous-reading.md), [reading experience](../../../../apps/chronicle/docs/reading-experience.md). Dependency and file ownership: [initiative index](README.md).

## Acceptance

- [ ] 回溯事件预览不改变当前时间，active unit/time/context 一致；未知段不遗留前段人物或年份。
- [ ] 自然滚动不制造海量 history entries，A→B→Event→返回按正确层级和位置恢复。
- [ ] 刷新/深链接可 locate 远处目标，旧网络响应不把视口拉回；用户滚动可取消恢复。
- [ ] 存储失败或 token 失效不开放外部跳转、不冒称恢复到新版本/首段。

## Verification requirements

Run the checks specified in the linked Issue and the current [delivery guide](../../../development/task-completion.md). Record actual acceptance, test/CI results and any unavailable checks in the delivery PR.

## Progress Log

- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
