# 阅读与公开发布验收说明

阅读、历史叙事和人物状态不再拥有独立的当前 gate；它们都由
`apps/chronicle/acceptance/staged_gate.py` 从同一份整章 source pack 驱动。这样源文、翻译、
抽取、linking、审核、发布和公开读取共享同一个 `gate_runtime.ComposeStack` 生命周期，
不会出现第二套 fixture worker 或旧格式候选。

语义契约见 [continuous-reading.md](continuous-reading.md)、
[reading-experience.md](reading-experience.md)、[source-corroboration.md](source-corroboration.md)
和 [person-state-reading.md](person-state-reading.md)。规模种子
`apps/chronicle/acceptance/reading_scale_fixture.py` 只通过产品持久化 API，不能写 raw SQL。

## 当前 fixture gate

```bash
python3 -m unittest discover -s apps/chronicle/acceptance -p 'test_staged_gate.py' -v

python3 apps/chronicle/acceptance/staged_gate.py \
  --mode fixture \
  --env-file /tmp/chronicle-staged-test.env \
  --source-pack apps/chronicle/corpus/first-round/source-pack.json \
  --evidence-dir /tmp/chronicle-staged-offline \
  --browser-required
```

真实栈 gate 会通过 Studio HTTP 上传完整 source，排队 staged 0.4 job，处理 resolution 和
person-state review，原子发布 reading stream/catalog，再显式选择已发布章运行 facts/prose
综合审核。公开接口读取必须保留 `version`、`paragraph_id`、`phase_id`、人物状态和原文
anchor；只读 source stream、截图或 mock HTTP 不算通过。

同一 gate 的程序矩阵覆盖：首尾 unit、别名和同一人物跨来源、来源隔离、状态阶段、原文
quote/event anchor、重试、取消、lease takeover、重启继续、原子发布及失败不泄漏半成品。
脚本只断言结构、引用和接口契约；完整章节和输出的翻译质量、同名不同人、来源独立性及
人物/历史判断必须由人工逐章阅读并单独记录，fixture 结果不得冒充内容证据。

浏览器 driver 为 `webapp/scripts/reading-flow-smoke.mjs` 和
`webapp/scripts/person-state-flow-smoke.mjs`，对应 suites 由 manifest 选择。CI 通过同一
`staged-gate` job 用 `--browser-required`；`--skip-browser` 仅供本地调试。性能证据继续
记录 active/restore p95、长任务、定位请求和有界挂载规模。

## Live 交接

```bash
python3 apps/chronicle/acceptance/staged_gate.py \
  --mode live \
  --env-file .env.chronicle \
  --source-pack apps/chronicle/corpus/first-round/source-pack.json \
  --evidence-dir /tmp/chronicle-staged-live
```

Live 不接受 fixture pack、fixture model、自动裁决或非交互终端；需要真实 provider、真实
模型名和人工审核。当前实现只完成严格 preflight/`READY` 交接，未在本地执行真实 provider
调用、人工审核、真实内容阅读或浏览器走查；缺少这些条件时必须明确记为未完成。

栈由共享 `gate_runtime` 隔离并在 gate 结束清理。当前 CI、运行说明和代码入口均只指向
staged 0.4；旧轮次的任务和回归语料仅作为历史背景。
