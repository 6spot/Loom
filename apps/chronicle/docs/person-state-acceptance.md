# 第三轮人物阶段资料自动验收运行说明

状态：C2-R3-T14 实施。语义归
[person-state-reading.md](person-state-reading.md) §2–§9，综合正文与两次审核归
[source-corroboration.md](source-corroboration.md)，审核队列归
[review-workflow.md](review-workflow.md)。本文是第三轮的统一运行说明；
第一轮见 `chapter-acceptance.md` / `final-acceptance.md`，第二轮见
`reading-acceptance.md`。T15 的真实内容验收接力在本文 §3。

## 入口

- `apps/chronicle/acceptance/third_round_gate.py`：统一薄入口，`--mode fixture|live`。
- `apps/chronicle/acceptance/gate_runtime.py`：与第一/第二轮 gate 共享的隔离 Compose /
  隔离 PostgreSQL / Studio / HTTP / 证据生命周期；第三轮只扩展了通用
  `free_port` / `write_compose_override` / `compose_config_check` /
  `require_interactive_stdin`，以及在
  `reviews_for_job` 上显式传入 `review_scope`（省略时产品只返回 resolution）。
- `apps/chronicle/webapp/scripts/person-state-flow-smoke.mjs`：真实栈上的整合
  人物阶段浏览器 driver，复用第二轮的 `SuiteRunner` / `p95`。
- `apps/chronicle/webapp/tests/reading-browser/integration/person-states/**`：
  manifest 契约与 `reading` / `review` / `performance` 三个 suite。
- 组件层场景仍由 T01 注册的 `--suite r3-harness|person-states|person-state-review|r3-all`
  覆盖；`r3-all` 在任一组件场景缺失时显式失败。

## 前置

```bash
mise install
python3 -m pip install -r apps/chronicle/persistence/requirements.txt \
  -r apps/chronicle/read_api/requirements.txt
npm --prefix apps/chronicle/webapp ci
npx --prefix apps/chronicle/webapp playwright install --with-deps chromium
docker build -f apps/chronicle/Dockerfile -t loom-chronicle:local .
```

## 1. 单元/边界测试（离线，CI）

```bash
python3 -m unittest discover -s apps/chronicle/acceptance -p 'test_third_round_gate.py' -v
python3 -m unittest discover -s apps/chronicle/corpus -p 'test_third_round_cases.py' -v
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_person_state_contract_unit.py' -v
```

`test_third_round_gate.py` 证明 fixture provider 产出的 0.3 候选通过 owning
`person_state_contract` 校验、fixture 综合草稿通过 `narrative_contract.validate_facts`
与 `validate_prose`（含来源已审核阶段资料进入综合事实），并覆盖
no-direct-write、fixture/live env guard、browser manifest fail-closed、live CLI
拒绝 `--auto-decide/--non-interactive/--execute` 与非 TTY。

## 2. 真实栈 fixture gate（默认含浏览器）

```bash
printf '%s\n' \
  'CHRONICLE_POSTGRES_PASSWORD=test-only' \
  'CHRONICLE_ADMIN_USER=admin' \
  'CHRONICLE_ADMIN_PASSWORD=test-only' \
  > /tmp/chronicle-r3-test.env

python3 apps/chronicle/acceptance/third_round_gate.py \
  --mode fixture \
  --env-file /tmp/chronicle-r3-test.env \
  --source-pack apps/chronicle/corpus/first-round/source-pack.json \
  --evidence-dir /tmp/chronicle-r3-fixture \
  --browser-required
```

gate 会：

1. 用 `gate_runtime.ComposeStack`（`chronicle-gate-r3-*`）起隔离栈：PG18 + Rust
   `chronicle-server` 前端 + Python `read_api` sidecar + durable worker，并起进程内
   确定性 HTTP provider（`host.docker.internal`）。provider 对 chapter prompt 返回
   0.3 候选（译文 + C0 记录 + reading 标注 + `person_states`），对综合 `present`
   prompt 返回确定性 facts/prose 草稿。模型名 `gate-fixture:person-state-chapter` /
   `gate-fixture:narrative` 使 worker 选择 0.3。
2. 经真实 Studio HTTP 上传四份冻结源、排队 0.3 job；身份 resolution 完成后 job 按章
   停在 `chapter_state_evidence` 包。gate 显式提交 person-state 决定（`default_assessment`
   显式声明 + plan 级 rationale），resume 后由唯一发布事务原子写入 catalog /
   chapters / reading index / person-state manifest。**不写任何 raw SQL、不 mock HTTP、
   不跳过审核环节。**
3. 经 Studio `GET /jobs/history/sources` 显式选择已发布章，`POST /jobs/history` 创建
   现有综合 job；分别通过 facts 审核（显式覆盖全部 `reviewed_conclusion_ids`）与
   prose 审核后发布。
4. 经公开 HTTP 读回正式 HistoryPage
   （`/history`、`/history/paragraphs`、`/history/conclusions/{id}`），记录
   `version/paragraph_id/phase_id/entity_id/state_id`、结论与原文 `anchor_id/quote`；
   并验证同一 version 的独立人物页读取（`at=<paragraph_id>` 返回同一 phase）。
   仅有 source stream、ReadingPage 或截图不算通过。
5. 负例/故障矩阵（`manifest.faults`）：链中失败不泄漏公开半成品、重启后已发布
   版本与人物锚点不变、未知 version/paragraph fail closed、source-only 结论不能冒充
   历史结论。产品侧的完整状态漂移 / 计划指纹 / 部分发布回滚由
   `apps/chronicle/worker/test_person_state_pipeline_postgres.py` 在同一 CI job 覆盖。
6. 注入合成的 5,000 units / 1,000 groups 规模集（产品持久化 API，非 raw SQL）。
7. 为浏览器审核 suite 停放一个真实 source job（停在 person-state 包）与一个真实
   综合 job（停在 facts），再运行 `person-state-flow-smoke.mjs --suite all`：
   - `reading`：真实 HistoryPage 定位、phase ready 且 `version/paragraph_id/phase_id`
     一致、两档明确性标记、键盘进入人物页、人物页 phase 一致、原位返回保留
     `version/at`、移动端紧凑面板、来源 ReadingPage 人物状态可达；四 viewport /
     200% 字体 / 触屏 / 草稿 / 409 由组件 `r3-all` 覆盖。
   - `review`：真实 Studio 混合队列同时暴露「阶段依据」与「事实核对」表单，分别可
     打开并从浏览器输入草稿。
   - `performance`：已取数据后人物区域更新 p95 ≤100ms，且无 ≥200ms 主线程任务，
     挂载上下文实体数有界。

`manifest.json` 的 `criteria` 逐项记录
`source_person_state_publish_chain/composite_history_two_review_chain/`
`published_history_and_person_page/negative_faults/browser_interaction/performance_budget`；
`history`/`source_person` 记录固定版本锚点，`works` 记录来源发布，`review_decisions`
记录每个审核决定，`browser.results[performance].evidence` 记录 p95 与 long task。
`--skip-browser` 仅供本地迭代；CI 使用 `--browser-required`。

## 3. live 模式（T15 交付）

```bash
python3 apps/chronicle/acceptance/third_round_gate.py \
  --mode live \
  --env-file .env.chronicle \
  --source-pack apps/chronicle/corpus/first-round/source-pack.json \
  --evidence-dir /tmp/chronicle-r3-live
```

live 严格禁用 `CHRONICLE_MODEL_FIXTURE_PACK`/`CHRONICLE_CHAPTER_FIXTURE_PACK`，要求
`CHRONICLE_CHAPTER_MODEL` 与 `CHRONICLE_NARRATIVE_MODEL`、无内嵌凭据的 endpoint 与
交互式终端，只输出 READY 交接（`provider_calls_by_t14=0`）。**live 不自动接受身份或
阶段审核，也不套用 fixture 的固定决定**；真实 provider 调用与逐项人工核对由 T15 在
受控会话中执行，并用同一个 HistoryPage / 人物页 / 审核队列入口逐案记录。

2026-09-12 的首次 T15 现场运行证据见
[`corpus/third-round/acceptance/README.md`](../corpus/third-round/acceptance/README.md)。
该次 preflight 为 `READY`，但真实《先主传》0.3 初稿／纠错稿仍违反 anchor 与译文
block 限制，来源 job 在 extract 阶段 fail closed；来源审核、综合两次审核、发布、
最终读取和真实浏览器走查均被阻断。逐案结论为真实 13 案 `BLOCKED`、synthetic 6 案
`NOT_RUN`，因此第三轮验收未通过；不得引用 T14 fixture PASS 补齐这些结果。

## fixture 机制与 live 内容判断的区别

fixture 模式只证明机器整链、审核交互与浏览器/性能机制可复现，**不是真实模型、
真实后端或已发布内容正确性的证据**（`manifest.disclaimer`）；D01 的 19 个案例
（13 真 + 6 合成）是人工内容核对预期。真实翻译、人物阶段结论、来源分歧与阅读体验
由 T15 处置，不得用 fixture PASS 代替。

## 多章 unit phase 投影一致性

来源发布按 reading unit 编译人物阶段。修复前，逐 unit 编译未把 revision 级的
`person_states` 证据限定到该 unit 所属章，其他章的 phase 因无排序边被当作
`order_unknown` 一并投影，导致 unit 暴露出不属于其上下文的人物，来源阅读接口按设计
以 `409 inconsistent` 失败关闭。修复：`resolve_publish.build_person_state_manifest` 把
unit 的 `chapter_id` 传入 `compile_person_state_projection`，投影按章限定证据
（同章未知顺序仍保留为 `order_unknown`）。回归由
`test_person_state_projection_unit.py::ChapterScopeTests` 覆盖。

门禁把该一致性作为硬条件：`criteria.multi_chapter_source_state_consistency` 必须为
`PASS`；只要任一已发布 unit 的来源人物读取返回 409，gate 立即以
`multi_chapter_source_state_consistency != PASS` 失败关闭并在 partial manifest 记录
stream/unit/person/phase 证据，绝不发布整体 PASS。`chronicle.yml` 的 third-round
manifest 断言同样要求该 criterion 为 `PASS`。

## 隔离栈与清理

`ComposeStack` 以 `COMPOSE_PROJECT_NAME=chronicle-gate-r3-*` 和全新
`CHRONICLE_DATA_DIR` 启停，`down -v` 清理；不会触碰操作者的默认 Compose 项目或
仓库管理的 PG 测试服务。gate 的 `finally` 在成功和失败时都停 provider 并清理栈
（`--keep-stack` 除外）。容器生成的 root 属主残留可用
`docker run --rm -v <dir>:/x alpine rm -rf /x/*` 清理。
