# 第二轮阅读自动验收运行说明

状态：C2-R2-T16 实施。语义归 [continuous-reading.md](continuous-reading.md)，
布局/恢复/预算归 [reading-experience.md](reading-experience.md)。本文是第二轮的
唯一运行说明；第一轮验收仍见 `chapter-acceptance.md` / `final-acceptance.md`。

## 入口

- `apps/chronicle/acceptance/second_round_gate.py`：统一薄入口，`--mode fixture|live`。
- `apps/chronicle/acceptance/gate_runtime.py`：与第一轮 gate 共享的 Compose/隔离库/
  Studio/HTTP/证据生命周期。
- `apps/chronicle/webapp/scripts/reading-flow-smoke.mjs`：真实栈上的整合浏览器 driver。
- `apps/chronicle/webapp/tests/reading-browser/integration/**`：manifest 契约与
  flow/accessibility/performance 三个 suite。

## 前置

```bash
mise install
python3 -m pip install -r apps/chronicle/persistence/requirements.txt
npm --prefix apps/chronicle/webapp ci
npx --prefix apps/chronicle/webapp playwright install --with-deps chromium
bash tools/postgres-test.sh up      # 仓库管理的 PG18 控制服务 127.0.0.1:15432
```

## 1. 单元/边界测试（离线，CI）

```bash
python3 -m unittest discover -s apps/chronicle/acceptance -p 'test_second_round_gate.py' -v
python3 -m unittest discover -s apps/chronicle/acceptance -p 'test_first_round_gate.py' -v
```

## 2. 离线整链 gate（真实 Python/PG + fixture provider）

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
  --evidence-dir /tmp/chronicle-r2-offline
```

fixture 模式在 PG18 控制服务上创建隔离库、应用产品迁移，用生产 `chapter_plan`
规划冻结源包、构造逐字 grounded 的 0.2 整章 fixture pack，经
`worker.run_once`（显式注入 `FixtureReadingChapterModel`）跑完
extract/assemble/resolve/publish，再经生产 T07/T08 读入口读回
stream/units/groups/locate/event preview/targets，并做失败注入。它：
- 不直接写产品表（仅隔离库 provisioning 与只读 SELECT 使用 psycopg）；
- 输出 `manifest.json` 与 `browser-fixture-manifest.json`；
- 明确标记 `fixture_only` 与非 live 免责声明。

`--allow-dirty` 仅供本地迭代；CI/验收必须干净 checkout。

## 3. 整合浏览器 gate（真实栈）

`reading-flow-smoke.mjs` 只操作仍在运行的栈，需要同一栈的数据库包含第 2 步发布的
stream（manifest 中的 `stream_id`/`catalog_sha`）：

```bash
python3 apps/chronicle/acceptance/second_round_gate.py \
  --mode fixture \
  --env-file /tmp/chronicle-second-round-test.env \
  --source-pack apps/chronicle/corpus/first-round/source-pack.json \
  --evidence-dir /tmp/chronicle-r2-offline \
  --base-url http://127.0.0.1:18080

# 或只跑 driver：
node apps/chronicle/webapp/scripts/reading-flow-smoke.mjs \
  --base-url http://127.0.0.1:18080 \
  --fixture-manifest /tmp/chronicle-r2-offline/browser-fixture-manifest.json \
  --suite flow|accessibility|performance|all \
  --output /tmp/chronicle-r2-browser
```

`flow` 覆盖滚动/active unit/事件预览/深链接/刷新/失效 locator；`accessibility`
覆盖四个 viewport、200% 字体/缩放、键盘、reduced-motion、44px 控件与 WCAG AA 对比度；
`performance` 覆盖 active→侧栏 p95、restore p95、mounted unit 上界、Long Task 与
5000 units/1000 groups 合成集。缺 manifest/scene/合成集会显式失败，不会静默 PASS。

## 4. live 模式（T17 交付）

```bash
python3 apps/chronicle/acceptance/second_round_gate.py \
  --mode live \
  --env-file .env.chronicle \
  --source-pack apps/chronicle/corpus/first-round/source-pack.json \
  --evidence-dir /tmp/chronicle-r2-live
```

live 严格禁用 `CHRONICLE_MODEL_FIXTURE_PACK`/`CHRONICLE_CHAPTER_FIXTURE_PACK`，要求
完整 provider 身份（含 `CHRONICLE_CHAPTER_MODEL`）与交互式终端，只输出 READY 交接；
真实 provider 调用与人工审核由 T17 在受控会话中执行，人工核对期间保留隔离栈。

## 隔离栈与清理

`gate_runtime.ComposeStack` 以 `COMPOSE_PROJECT_NAME=chronicle-gate-*` 和全新
`CHRONICLE_DATA_DIR` 启停，`down -v` 清理；不会触碰操作者的默认 Compose 项目或
仓库管理的 PG 测试服务。隔离数据库在 gate 结束时 `DROP DATABASE ... WITH (FORCE)`。

## 边界与已知未验证项

- 第一轮 `first_round_gate.py` 保留原语义，仅改用 `gate_runtime` 的共享 helper；
  生产契约与性能阈值未放宽。
- 0.2 整章链在 fixture 模式经产品 Python 入口 + PG 跑通；Rust HTTP 前端与浏览器
  行为需要已运行的栈，本任务实现 driver/manifest/CI 接线，真实栈运行证据由
  T17 汇总。
- 5000 units/1000 groups 合成集必须由 `performance` suite 在真实栈上测量；
  gate 在缺该集时显式记录 `not_measured` 并保持门禁失败，不伪造通过。
- worker 的 `CHRONICLE_CHAPTER_FIXTURE_PACK` 当前只选择 0.1 fixture provider；
  经 Compose worker 跑 0.2 fixture 需要 T03/T06 增加注入点，属超出本任务写入
  边界的改动，已按 `second_round_gate.py` 的显式注入路径规避。
