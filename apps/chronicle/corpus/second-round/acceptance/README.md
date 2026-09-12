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
- [`run-live-r2-20260912-v6.json`](run-live-r2-20260912-v6.json)：新增完整章语义
  指导后的同模型回归；首稿抽取全空，一次纠错后仍有三个机械引用错误。
- [`candidate-live-r2-20260912-v6.json`](candidate-live-r2-20260912-v6.json)：该次
  完整请求、两稿、实际 prompt、校验报告和用量；可重放，未写库或发布。
- [`reading-review-20260912-v6.md`](reading-review-20260912-v6.md)：重新逐段通读
  的独立内容 FAIL 报告，分别列出旧错修复、新旧共有问题、退化及解释疑点。
- [`preflight-live-r2-20260912-v6.json`](preflight-live-r2-20260912-v6.json)：该次
  canonical live 预检原始记录，`READY` 仅表示执行条件满足；实际调用单独记录。
- [`run-live-r2-20260912-sol-v6.json`](run-live-r2-20260912-sol-v6.json) 与
  [`完整请求及失败记录`](candidate-live-r2-20260912-sol-v6.json)：同一 v6 请求
  改用 Sol，单次约 908 秒后无 output text；无终稿，不能评价翻译质量。
- [`run-live-r2-20260912-deepseek-v6.json`](run-live-r2-20260912-deepseek-v6.json) 与
  [`完整请求及失败记录`](candidate-live-r2-20260912-deepseek-v6.json)：用户指定的
  `deepseek-v4.1-flash` 非流式对照；返回 incomplete，输出接近 65,536 token
  上限，其中 31,751 为推理 token；未接受产物，未评定内容质量。
- [`run-live-r2-20260912-deepseek-low-v6.json`](run-live-r2-20260912-deepseek-low-v6.json)
  与 [`完整请求及失败记录`](candidate-live-r2-20260912-deepseek-low-v6.json)：同章
  请求 CPA 的 `(low)` 后缀，约 282 秒后仍因 `max_output_tokens` 中止；服务
  报告输出 65,537，其中推理 63,773。原样保留用量，不假定下游采用了 low。
- [`run-live-r2-20260912-deepseek-128k-v6.json`](run-live-r2-20260912-deepseek-128k-v6.json)
  与 [`完整请求及失败记录`](candidate-live-r2-20260912-deepseek-128k-v6.json)：仅将
  完整章 provider 输出预算改为 131,072，同步 request/fingerprint；服务仍在
  65,536 输出 token 时返回 `incomplete/max_output_tokens`，没有完整候选。
  这不能确定限制由 CPA 或哪个上游环节施加，也不能评价翻译质量。
- [`provider-diagnostics-20260912-deepseek.json`](provider-diagnostics-20260912-deepseek.json)：
  四个小型严格 JSON 请求的可用性及推理参数观察；均成功，但无法确认下游
  推理控制生效。它们与完整章调用分开计数，不构成章节验收。

## 最近重跑结论（2026-09-12）

**未通过。** v6 同模型回归首稿没有返回实体、事件或 Claim；唯一纠错后仍有
三个引用错误，整份产物拒绝。41 段、13,728 字符前后保留，但独立完整内容复核
发现人物关系反转、整条嵌注及奏表论据遗漏。已有明确源历日期的段落也全部被标为
未知时间，人物和事件阅读关联全空。部分旧错修复不抵消这些问题，不据单次对照
宣称提示或模型的普遍效果。本次两次调用共报告 128,583 tokens，账单费用未知。

换用 Sol 及 DeepSeek 的对照都未返回完整候选；DeepSeek 的小请求成功不代表
完整章能完成，单纯增加本地输出预算也未解除本次截断。各次请求、用量和终止
原因分别归档，没有截断原章、接受半份产物或自动审核／发布。

此前 v5 单章回归在一次纠错后通过机械校验，41 段正文、15,943
字符前后完全一致；7 条初稿诊断全部进入纠错提示。独立内容复核仍发现确定的
人物指代、句意和引文错误及漏译。`accepted=true` 仅指联合产物通过结构与纠错
检查，不能当成内容质量或发布许可。本次未写库、审核或发布，不替代四章整链
及浏览器验收；#586、#549 保持未验收，R3 另行验收。

此前 v4 的《先主傳》在初稿和一次纠错后仍不合法；修正稿合并了段落、删除
事件 span，并遗漏具体内容。各次运行的完整失败证据分别保留，不覆盖旧结论。

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
