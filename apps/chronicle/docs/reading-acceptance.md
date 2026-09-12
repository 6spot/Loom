# 第二轮阅读自动验收运行说明

状态：C2-R2-T16 实施。语义归 [continuous-reading.md](continuous-reading.md)，
布局/恢复/预算归 [reading-experience.md](reading-experience.md)。本文是第二轮的
唯一运行说明；第一轮验收仍见 `chapter-acceptance.md` / `final-acceptance.md`。

## 入口

- `apps/chronicle/acceptance/second_round_gate.py`：统一薄入口，`--mode fixture|live`。
- `apps/chronicle/acceptance/gate_runtime.py`：与第一轮 gate 共享的隔离 Compose /
  隔离 PostgreSQL / Studio / HTTP / 证据生命周期。
- `apps/chronicle/acceptance/reading_scale_fixture.py`：明确合成的
  5,000 units / 1,000 groups 规模集种子。它只用产品持久化 API
  （`chapter_store.record_accepted_chapter_fenced` /
  `chapter_store.persist_chapter_publication` /
  `reading_store.persist_reading_stream` / `canonical_store.persist_catalog`），
  不写任何 raw SQL。
- `apps/chronicle/webapp/scripts/reading-flow-smoke.mjs`：真实栈上的整合浏览器 driver。
- `apps/chronicle/webapp/tests/reading-browser/integration/**`：manifest 契约与
  flow/accessibility/performance 三个 suite。

## 前置

```bash
mise install
python3 -m pip install -r apps/chronicle/persistence/requirements.txt
npm --prefix apps/chronicle/webapp ci
npx --prefix apps/chronicle/webapp playwright install --with-deps chromium
docker build -f apps/chronicle/Dockerfile -t loom-chronicle:local .
```

## 1. 单元/边界测试（离线，CI）

```bash
python3 -m unittest discover -s apps/chronicle/acceptance -p 'test_second_round_gate.py' -v
python3 -m unittest discover -s apps/chronicle/acceptance -p 'test_first_round_gate.py' -v
```

`test_second_round_gate.py` 另含 `assert_time_contract`、negative manifest 校验、
scale fixture 无 raw write 与 scope guard。

## 2. 真实栈 fixture gate（默认含浏览器与性能）

```bash
printf '%s\n' \
  'CHRONICLE_POSTGRES_PASSWORD=test-only' \
  'CHRONICLE_ADMIN_USER=admin' \
  'CHRONICLE_ADMIN_PASSWORD=test-only' \
  > /tmp/chronicle-second-round-test.env

python3 apps/chronicle/acceptance/second_round_gate.py \
  --mode fixture \
  --env-file /tmp/chronicle-second-round-test.env \
  --source-pack apps/chronicle/corpus/first-round/source-pack.json \
  --evidence-dir /tmp/chronicle-r2-offline \
  --browser-required
```

gate 会：
1. 用 `gate_runtime.ComposeStack` 起隔离 Compose 栈（PG18 + Rust `chronicle-server`
   前端 + Python `read_api` sidecar + durable worker），并起进程内确定性 0.2 fixture
   模型 HTTP provider（`host.docker.internal`）。gate 使用 `gate-fixture:reading-chapter`
   明确选择 0.2；worker 将同一版本传入请求与 provider strict schema，避免当前生产默认
   0.3 与 R2 fixture 混用。普通生产模型仍默认 0.3。
2. 经真实 Studio HTTP（Rust 前端）上传冻结源、排队、处理 `needs_review`
   （fixture 固定决定）并发布。
3. 经公开 HTTP 读回 stream/units/groups/locate/event preview+targets，并做未知
   locator/stream/snapshot 负例；发布第二个 revision 形成版本场景。
4. 注入确定性链中失败（无公开半成品）、重启后公开 stream 不变。
5. 用产品持久化 API 注入合成的 5,000/1,000 规模集，并对单位/组 DTO 跑
   `reading_contract.validate_reading_dto` 与 gate 的 `assert_time_contract`
   （unknown-mode 空 `event_refs` 合法；events/mixed-mode 空 `event_refs` 拒绝）。
6. 定位并写入显式负例：未知时间、缺失当前上下文（且前一段有上下文以证明清空）、
   有实体但无来源角色，并在 `manifest.negatives` 校验。
7. 运行 `reading-flow-smoke.mjs --suite all`：多 stream、版本固定、事件预览
   hover/keyboard/touch、角色、时间轴、导航负例、触屏面板、reduced-motion、
   200% 字体、四 viewport、44px、对比度、unknown/missing role/time 负例；性能在
   固定 Chromium/viewport 下执行 5 次，每次先逐段推进 1,000 次，确认每次相邻
   active unit 更新且挂载数有界，再连续滚动 30 秒，每 5 秒检查仍在前进；
   同页定位已回收段落并后退恢复；再通过侧轴跳到尚未缓存的末区段，连续向前文
   读 40 段、向后文读 35 段，跨越 locate 页边界，不能靠刷新页面绕过窗口；记录每次与总体的
   active/restore p95。active 从浏览器 wheel 输入计时，直到新正文 active 与侧栏
   对应同一 unit，作为 active 到侧栏更新的保守上界，仍使用原 100ms 预算；不能
   用 MutationObserver 回调时刻抹去同一 JS task 中的同步耗时。恢复从目标 locate
   响应完成（含 page）计时，直到目标 active、侧栏一致且滚动位置正确稳定。
   跨过的 ordinal 数不能代替逐段推进次数。

定位恢复计时从文档加载前注册的 `PerformanceObserver` 取得真实 locate 请求的
`responseEnd`，仅保留最近 64 条定位记录；长文阅读填满浏览器默认资源计时缓冲区
也不能丢失后续定位计时。缺少实际请求记录仍失败，不用当前时间补值。探针的
Chromium 回归会主动填满资源缓冲区，并检查导航后不会沿用上一文档的记录：

```bash
node apps/chronicle/webapp/tests/reading-browser/integration/locate-timing-smoke.mjs
```

`manifest.json` 的 `criteria` 逐项记录
`real_stack_offline_chain/negative_faults/browser_interaction/performance_budget`，
`faults` 记录 6 项失败关闭（含 role/time 契约），`scale_contract` 记录合成集 DTO
校验，`negatives` 记录三类负例单元，`browser.results[performance].evidence.runs`
记录 5 次测量。`--skip-browser` 仅供本地迭代；CI 使用 `--browser-required`。

## 3. live 模式（T17 交付）

```bash
python3 apps/chronicle/acceptance/second_round_gate.py \
  --mode live \
  --env-file .env.chronicle \
  --source-pack apps/chronicle/corpus/first-round/source-pack.json \
  --evidence-dir /tmp/chronicle-r2-live
```

live 严格禁用 `CHRONICLE_MODEL_FIXTURE_PACK`/`CHRONICLE_CHAPTER_FIXTURE_PACK`，要求
完整 provider 身份（含 `CHRONICLE_CHAPTER_MODEL`）与交互式终端，只输出 READY 交接；
真实 provider 调用与人工审核由 T17 在受控会话中执行。

## 4. 发布原子性补充证据

生产 worker 的 `--fail-stage` 只作用于 legacy fake executor，无法在真实 0.2
publish 阶段注入失败。发布事务的“失败不泄漏半成品”由产品拥有的
`apps/chronicle/worker/test_reading_pipeline_postgres.py` 的
`test_publish_faults_leave_no_partial_public_content` 覆盖，CI 同 job 运行：

```bash
python3 -m unittest discover -s apps/chronicle/worker \
  -p 'test_reading_pipeline_postgres.py' -v -k publish_faults
```

## 隔离栈与清理

`ComposeStack` 以 `COMPOSE_PROJECT_NAME=chronicle-gate-*` 和全新
`CHRONICLE_DATA_DIR` 启停，`down -v` 清理；不会触碰操作者的默认 Compose 项目或
仓库管理的 PG 测试服务。gate 尽最大努力移除 `stack-data`（容器生成的 root
属主文件可能残留，可用 `docker run --rm -v <dir>:/x alpine rm -rf /x/*` 清理）。
