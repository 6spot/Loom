---
task: C2-R2-T02
issue: 571
kind: leaf
parent: C2-R2
status: planned
depends_on: [C2-R1-T02]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 真实阅读样例与独立组件浏览器基座

## Scope

[Issue #571](https://github.com/6spot/Loom/issues/571) owns the bounded implementation steps. 准备后续组件共享的可核对阅读场景和浏览器测试基座，避免各任务自造时间、人物和导航数据。

Canonical contracts: [continuous reading](../../../../apps/chronicle/docs/continuous-reading.md), [reading experience](../../../../apps/chronicle/docs/reading-experience.md). Dependency and file ownership: [initiative index](README.md).

## Acceptance

- [ ] 12 个真实核对点能在第一轮已冻结原件中重定位；每个人工合成场景有明确标签。
- [ ] walkthrough 体现回溯不切当前时间、跨来源显式切换与返回，未把注释当正文断言。
- [ ] harness suite 在真实 Chromium 打开 fixture 页面并操作成功；缺失组件 suite 不会假 PASS。
- [ ] 基座不挂接生产路径、不引入新 package、不修改 dist，其他任务可各写独立 scene/spec。

## Verification

Not run. Implementation has not started. During delivery record actual test/CI evidence and any unavailable checks. Cross-round governance includes the first-round and second-round records as described in [task-completion](../../../development/task-completion.md#dependencies-across-initiative-directories).

## Progress Log

- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
