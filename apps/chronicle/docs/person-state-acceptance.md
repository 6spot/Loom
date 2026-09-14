# 人物阶段与历史发布验收说明

当前人物阶段验收与篇章、阅读、历史发布共用唯一入口
`apps/chronicle/acceptance/staged_gate.py`，使用 staged 0.4 的真实生产 worker 链路和
`gate_runtime.ComposeStack`。不再复制旧轮次的启动方式、raw DB 写入或 fixture worker。

## 运行

```bash
python3 -m unittest discover -s apps/chronicle/acceptance -p 'test_staged_gate.py' -v
python3 -m unittest discover -s apps/chronicle/corpus -p 'test_third_round_cases.py' -v
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_person_state_contract_unit.py' -v

python3 apps/chronicle/acceptance/staged_gate.py \
  --mode fixture \
  --env-file /tmp/chronicle-staged-test.env \
  --source-pack apps/chronicle/corpus/first-round/source-pack.json \
  --evidence-dir /tmp/chronicle-staged-offline \
  --browser-required
```

唯一 worker fixture 位于 `apps/chronicle/worker/staged_pipeline_fixture.py`，只响应完整
staged prompt，并把候选标记为 0.4；它不制造接受产物、不写产品表、不跳过审核。真实栈
必须通过 Studio 上传和 queue API，经过 identity/phase/facts/prose review，再由产品发布
事务生成 catalog、reading index、history 和 person-state projection。

程序证据包括原文 quote 与 event anchor、source/person scope、每阶段 step history、review
decision、acceptance receipt、HistoryPage 与人物页的 version/paragraph/phase 对齐，以及
重试、取消、lease takeover、重启继续、原子发布和无半成品。浏览器 suite 检查审核表单、
阶段切换、来源读取和性能边界。

内容质量单独验收：人工必须完整阅读每个 source chapter 和全部输出，核对译文、首尾段、
别名、同一人物跨两份来源、同名不同人、状态阶段、来源分歧、原文引用和事件锚点。脚本
只能验证结构和程序契约，不能据 fixture PASS 推断历史事实或模型质量。

## Live 状态

```bash
python3 apps/chronicle/acceptance/staged_gate.py \
  --mode live \
  --env-file .env.chronicle \
  --source-pack apps/chronicle/corpus/first-round/source-pack.json \
  --evidence-dir /tmp/chronicle-staged-live
```

Live 严格拒绝 fixture pack/model、自动决定和非交互会话，且 endpoint 不得内嵌凭据或查询
秘密。当前代码只执行 provider/Compose/source-pack preflight 并生成 `READY`；真实 provider
调用、人工审核、完整内容阅读和浏览器现场尚未完成。不得用 fixture 或 `READY` 补齐 live
验收结果。

默认 gate 结束时清理隔离 Compose 栈（`down -v`）；仅在同一受控会话需要浏览器时使用
`--keep-stack`，完成后手工清理。
