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
- [ ] 元数据纠错保留原有段落 ID、顺序及全文；缺尾、段落超限、重复 ID 等真正结构错误仍可完整修复。规则同时覆盖 R3 共用入口的 0.3。
- [ ] 两稿及独立纠错检查均可重放；仅正文保留检查失败也必须拒绝整份产物，不能拼回旧正文后当作模型成功。历史版本按原规则重放。
- [ ] 2026-09-12 v4 失败样本的 16 条诊断全部进入纠错提示，同名多处匹配不误用第一处；真实内容质量仍由 T17 独立核对。

## Verification requirements

Run the checks specified in the linked Issue and the current [delivery guide](../../../development/task-completion.md). Record actual acceptance, test/CI results and any unavailable checks in the delivery PR.

## Progress Log

- 2026-09-12 — 针对 v5 内容失败，在同一完整章 prompt 增补主体承接、引文视角、古词、嵌注完整性及有证据 Claim 抽取指导（0.2 v6／0.3 v4）。不增加调用轮次或数量门槛；仅元数据纠错继续保留正文。旧 v5/v3 历史保留原机械重放规则。提示及离线检查不能证明内容已改善，真实回归结果由独立审查记录。
- 2026-09-12 — `20054a3` 的 0.2 prompt v5 单章真实回归：完整《先主傳》初稿加一次纠错后，7 条结构错误全部修复；41 段、15,943 字符逐段 ID／顺序／全文完全保留，历史可重放。独立内容复核仍失败，存在主体误配、古词误译及嵌注遗漏；不把机械 accepted 当作内容通过。两稿、用量与复核保存在 `apps/chronicle/corpus/second-round/acceptance/*20260912-v5*`。未写库或发布，不替代 T17 或 R3 验收。
- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
- 2026-09-12 — 增补已复现的纠错删文、诊断遗漏及历史重放要求。离线输入保留在 `apps/chronicle/corpus/second-round/acceptance/candidate-live-r2-20260912-v4.json`；其 28 段初稿纠错后缩为 1 段的失败不因结构测试通过而解除。
