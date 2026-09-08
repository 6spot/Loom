---
task: C2-R2-T16
issue: 585
kind: leaf
parent: C2-R2
status: planned
depends_on: [C2-R2-T15]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 离线整链、浏览器交互与长文性能验收接入 CI

## Scope

[Issue #585](https://github.com/6spot/Loom/issues/585) owns the bounded implementation steps. 用真实 Rust/Python/PG 和 fixture provider 证明整条阅读链及故障行为，把第二轮数据/交互检查接入现有 CI。

Canonical contracts: [continuous reading](../../../../apps/chronicle/docs/continuous-reading.md), [reading experience](../../../../apps/chronicle/docs/reading-experience.md). Dependency and file ownership: [initiative index](README.md).

## Acceptance

- [ ] 真实栈离线链通过，重启/发布失败不泄漏半成品；所有角色/时间/版本/导航负例被检验。
- [ ] 键盘/触屏/窄屏/200% 字体与 reduced-motion 实际操作有证据，不能只检查源码字符串。
- [ ] 5,000 units/1,000 groups 测量满足已定预算，或任务保持未完成并记录具体失败。
- [ ] CI 发现本轮路径且执行数据/UI/跨轮 ledger 检查；缺 fixture/场景/manifest 时 harness 失败。

## Verification

Not run. Implementation has not started. During delivery record actual test/CI evidence and any unavailable checks. Cross-round governance includes the first-round and second-round records as described in [task-completion](../../../development/task-completion.md#dependencies-across-initiative-directories).

## Progress Log

- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
