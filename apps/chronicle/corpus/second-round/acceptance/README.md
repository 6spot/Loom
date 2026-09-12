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
- [`run-live-r2-20260912-v4.json`](run-live-r2-20260912-v4.json)：修复后新库重跑，
  记录真实生成失败、调用次数与剩余验收缺口。
- [`candidate-live-r2-20260912-v4.json`](candidate-live-r2-20260912-v4.json)：完整
  原章 request、两稿候选、校验报告和实际纠错诊断，可离线重放。
- [`reading-review-20260912.md`](reading-review-20260912.md)：v4 独立复核，
  含三处具体删略的原文／初稿／修正稿对照。
- [`run-live-r2-20260912-v5.json`](run-live-r2-20260912-v5.json)：纠错修复后的
  单章真实生成回归，记录两次调用、token 用量及正文保留检查；没有写库或发布。
- [`candidate-live-r2-20260912-v5.json`](candidate-live-r2-20260912-v5.json)：该次
  完整请求、两份原始响应、实际 prompt、结构验证及纠错验证，可离线重放。
- [`reading-review-20260912-v5.md`](reading-review-20260912-v5.md)：该次独立内容
  复核；结构通过，但主语、古词和引文理解错误及漏译仍使内容验收失败。

## 最近重跑结论（2026-09-12）

**未通过。** 最新 v5 单章回归在一次纠错后通过机械校验，41 段正文、15,943
字符前后完全一致；7 条初稿诊断全部进入纠错提示。独立内容复核仍发现确定的
人物指代、句意和引文错误及漏译。`accepted=true` 仅指联合产物通过结构与纠错
检查，不能当成内容质量或发布许可。本次未写库、审核或发布，不替代四章整链
及浏览器验收；#586、#549 保持未验收，R3 另行验收。

此前 v4 的《先主傳》在初稿和一次纠错后仍不合法；修正稿合并了段落、删除
事件 span，并遗漏具体内容。两次运行的完整失败证据分别保留，不覆盖旧结论。

## 首次运行结论（2026-09-11）

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
