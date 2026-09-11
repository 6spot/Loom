# C2-R2-T17 真实章节阅读独立验收证据

任务：C2-R2-T17（GitHub [#586](https://github.com/6spot/Loom/issues/586)，
Multica LM-39），父任务 C2-R2（#549）。本目录保存第二轮**真实 provider
现场运行**的验收证据与独立内容复核输入。

- [`run-live-r2.json`](run-live-r2.json)：机器可读运行证据。含候选 commit、
  真实 provider 身份（不含凭据）、四个冻结章的源 hash/revision/job、发布
  stream/catalog、unit/group 计数、narrative_time 模式分布，以及 0.2 生成
  fail-closed 的原始错误与审核决定表。
- [`reading-review.md`](reading-review.md)：独立内容复核结论、逐复核点结果
  与未验证项。

## 本次结论

四章正文完整可读，但叙事时间、事件词与导航、当前人物地点均未由真实内容
满足：`year_key` 全 `unknown`、正文事件词 span 为 0、`context_entities` 为
0。真实内容验收**未通过**，本轮不成立；修复后需重跑。

## 如何复现

按 [`apps/chronicle/docs/reading-acceptance.md`](../../../docs/reading-acceptance.md)
第 3 节在受控、已授权的 live provider 环境运行：

```bash
python3 apps/chronicle/acceptance/second_round_gate.py \
  --mode live \
  --env-file <authorized-live.env> \
  --source-pack apps/chronicle/corpus/first-round/source-pack.json \
  --evidence-dir <evidence-dir>
```

live 严格禁用 fixture，要求完整 provider 身份（含 `CHRONICLE_CHAPTER_MODEL`）
与交互式终端，preflight 通过后只输出 `READY` 交接；真实 provider 调用、审核
和读回由本任务在受控会话中执行。运行内容与审核证据写入本目录，**不得提交任何
凭据**。

## 复核规则

逐点复核不得以 fixture PASS 或开发者自评代替；真实主叙事/回溯判断与时间、
事件、人物地点对应仍需人工或独立强复核者确认（见 `reading-review.md`
“未验证项”）。真实费用/密钥仅使用已授权环境。
