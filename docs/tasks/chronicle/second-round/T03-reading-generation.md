---
task: C2-R2-T03
issue: 572
kind: leaf
parent: C2-R2
depends_on: [C2-R2-T01, C2-R1-T19]
created_at: 2026-09-08
---

# 完整章联合生成阅读注解并接入 provider

## Scope

[Issue #572](https://github.com/6spot/Loom/issues/572) owns the bounded implementation steps. 让现有整章生产一次返回译文、提取和阅读注解，生产明确使用 0.2，保留统一有界修正和真实 provider 验证。

Canonical contracts: [continuous reading](../../../../apps/chronicle/docs/continuous-reading.md), [reading experience](../../../../apps/chronicle/docs/reading-experience.md). Dependency and file ownership: [initiative index](README.md).

## Acceptance

- [ ] 一次整章请求得到完整 0.2 联合产物，无按段或阅读时模型调用。
- [ ] 修正包含完整章，最多两次语义生成；修正仍失败则联合产物不接受。
- [ ] 不合法阅读 refs/角色/span 不能被丢弃后当成功；0.2 不降为 0.1。
- [ ] fingerprint 和 run 历史区分模型/契约/限制版本，provider/fixture 输出形状一致。

## Verification requirements

Run the checks specified in the linked Issue and the current [delivery guide](../../../development/task-completion.md). Record actual acceptance, test/CI results and any unavailable checks in the delivery PR.

## Progress Log

- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
