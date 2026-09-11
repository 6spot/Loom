---
task: C2-R2-T16
issue: 585
kind: leaf
parent: C2-R2
depends_on: [C2-R2-T15]
created_at: 2026-09-08
---

# 离线整链、浏览器交互与长文性能验收接入 CI

## Scope

[Issue #585](https://github.com/6spot/Loom/issues/585) owns the bounded implementation steps. 用真实 Rust/Python/PG 和 fixture provider 证明整条阅读链及故障行为，把第二轮数据/交互检查接入现有 CI。

Canonical contracts: [continuous reading](../../../../apps/chronicle/docs/continuous-reading.md), [reading experience](../../../../apps/chronicle/docs/reading-experience.md). Dependency and file ownership: [initiative index](README.md).

## Acceptance

- [ ] 真实栈离线链通过，重启/发布失败不泄漏半成品；所有角色/时间/版本/导航负例被检验。
- [ ] 键盘/触屏/窄屏/200% 字体与 reduced-motion 实际操作有证据，不能只检查源码字符串。
- [ ] 5,000 units/1,000 groups 测量满足已定预算，或任务保持未完成并记录具体失败。
- [ ] CI 发现本轮路径且执行数据/UI 检查；缺 fixture/场景/manifest 时 harness 失败。

## Verification requirements

Run the checks specified in the linked Issue and the current [delivery guide](../../../development/task-completion.md). Record actual acceptance, test/CI results and any unavailable checks in the delivery PR.

## File scope coordination (C2-R2-T16)

The issue's declared write boundary did not name a module for the synthetic
scale corpus required by the 5,000-unit/1,000-group budget. To avoid putting
scale construction inside the real-chain gate or a product-owned module, the
following acceptance-only file is added to this task's scope by explicit
coordination (recorded here and in the delivery PR):

- `apps/chronicle/acceptance/reading_scale_fixture.py` — explicitly synthetic
  5,000-unit/1,000-group scale stream seeded through the product persistence
  boundary (`chapter_store` / `canonical_store` / `reading_store`), with no raw
  SQL. The module carries a `SCOPE_HANDOFF` record and is guarded by
  `test_second_round_gate.py::test_scale_fixture_scope_handoff_recorded`.

Boundary changes beyond this file still require coordinator sync per the
initiative index.

## Progress Log

- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
- 2026-09-11 — Implemented the real-stack fixture gate, browser suites, CI wiring and the synthetic scale fixture. Recorded the `reading_scale_fixture.py` scope coordination above; 5,000/1,000 measurement and role/time/version/navigation negatives are enforced fail-closed.
