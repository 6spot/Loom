---
task: C2-R1-T18
issue: 568
kind: leaf
parent: C2-R1
status: in_progress
depends_on: [C2-R1-T17]
created_at: 2026-09-08
started_at: 2026-09-09
completed_at:
completion_pr:
merge_sha:
---

# 离线全链验收脚本、故障场景与CI接入

## Scope

[Issue #568](https://github.com/6spot/Loom/issues/568) owns the bounded implementation checklist. 在真实产品接口上一次验证本轮完整闭环及失败行为，提供下一任务可直接运行的真实模型验收入口。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 新空PG18/Compose经真实API和浏览器走通第一轮，所有列举故障得到期望结果。
- [x] fixture结果明确非live，live拒绝fixture/非交互自动决定，脚本不直写DB。
- [x] 失败和成功证据分开保留，有源码候选SHA和完整来源/产物定位。
- [x] 新验收guide命令可直接执行，CI paths命中并实际运行离线gate；C1历史记录未改写。

验收说明：离线门以真实产品入口（plan_chapters / T01 校验与接受 /
T07 装配 / T08 pair 与冻结计划指纹 / 真实 T11·T17 浏览器脚本与 Reader
路由复用）在冻结 T02 语料上走通全链及全部故障注入；首个框的空
PG18/Compose 真实上传→处理→审核→发布→浏览器阅读由 live READY 移交
T19 执行（T18 不调用真实 provider），故首框留待 T19 内容验收时关闭。

## Verification

- `python3 -m unittest discover -s apps/chronicle/acceptance -p 'test_first_round_gate.py' -v` — 10 tests OK (fixture 端到端 PASS 断言、live 六类拒绝、READY 零 provider 调用、无直写 DB、合成文本装配与故障闭环）。
- `python3 apps/chronicle/acceptance/first_round_gate.py --mode fixture --env-file /tmp/chronicle-first-round-test.env --source-pack apps/chronicle/corpus/first-round/source-pack.json --evidence-dir /tmp/chronicle-first-round-offline --allow-dirty` — PASS：2 works（三国志 3 章 + 通鑑 1 章，plan/切片绑定/接受/装配全经真实入口），10 故障注入全部 fail-closed，pair 初始 uncertain 且阻塞、batch 默认 uncertain，manifest 明确 fixture 非 live。`--allow-dirty` 仅本地迭代使用；CI 运行严格干净检出。
- live 拒绝路径已逐项验证：fixture pack 互斥、provider 缺失、endpoint 内嵌凭据、`--auto-decide`、`--non-interactive`、`--execute` 全部 FAIL；READY 移交记录 `provider_calls_by_t18=0`。
- `git diff --check` clean；`.github/workflows/chronicle.yml` YAML 解析通过。
- `python3 tools/validator_ready.py --root docs/tasks/chronicle/first-round --check --format json` — 仍报 `task C2-R1 has no status`（T16 已记录的根级问题，修复 `tools/validator_ready.py` 超出本任务文件所有权，未改）。
- 依赖对账：T17 交付 PR #612 已合入默认分支（`ad13925` 即 origin/main  HEAD，含 Reader 路由与 `chapter-reader-smoke.mjs`）；T17 台账自身的 `merge_sha` 回填归 T17 所有，本任务不碰其他任务台账。
- 未运行：空 PG18/Compose 真实 live 全链（归 T19）；新 `chronicle.yml` 的 Actions 实际运行待 PR CI。

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-09 — Implemented and locally verified (see Verification): `first_round_gate.py` fixture/live 编排入口、`test_first_round_gate.py`（10 tests）、`chapter-acceptance.md` 唯一新轮验收指南、`final-acceptance.md` 仅追加 C2 链接（C1 历史未改）、`.github/workflows/chronicle.yml` 离线 gate（fixture only，不恢复已退休 C1 live 工作流；`chronicle-docker.yml` 无需接入，fixture 不用 Docker）。`merge_sha`/`completed_at` 待合并后按需回填，不另开台账 PR。
