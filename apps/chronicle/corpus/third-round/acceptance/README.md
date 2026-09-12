# C2-R3-T15 真实人物阶段与阅读独立验收证据

任务：C2-R3-T15（GitHub [#633](https://github.com/6spot/Loom/issues/633)，
Multica LM-58），父任务 C2-R3（#550）。本目录保存第三轮真实 provider 现场运行、
逐案独立复核和失败分类；任何 `BLOCKED` / `NOT_RUN` 都不得计为通过。

- [`run-live-r3.json`](run-live-r3.json)：去敏机器证据，记录候选 commit、provider
  身份（不含凭据）、冻结来源、真实 job / run、两稿校验和每层 gate 结论。
- [`person-state-review.md`](person-state-review.md)：19 案逐项结果、真实与 synthetic
  分栏、失败归属、页面／手机／键盘／截图未验证原因。

## 本次结论（2026-09-12）

**未通过。** 严格 live preflight 在测试服务器、全新隔离数据目录和候选
`149af552705b9333d9c4c8de8eced83b8caa7eb1` 上返回 `READY`，随后真实 provider
处理三章完整《三國志》上传。首次 claim 的第一章初稿有 30 个 0.3 合同错误；一次
纠错降至 5 个，但仍有原文 anchor 指向错误 block、对应 `reading_context` anchor
错误，以及单个译文 block 15,507 code points（上限 8,192）。显式 retry 的初稿有
13 个错误，纠错后仍留 1 个非原文逐字 quote。worker 两次均按合同 fail closed；
最终允许的第三次 claim 初稿有 9 个错误，纠错调用又因 provider 响应无 output text
发生 transport failure。attempts 耗尽后的 job 状态是 `needs_review`，但公开审核队列为
空，不能提交身份或人物阶段决定。来源链没有进入
assemble、身份／阶段审核、来源发布或综合任务。

因此 13 个真实案例均为 `BLOCKED`，6 个 synthetic 反例为 `NOT_RUN`；没有
publication / stream / catalog / manifest、综合 facts / prose 决定、固定
`version / paragraph_id / phase_id`、人物页或原文返回，也没有可声称为真实结果的
桌面、手机、触屏、键盘或截图证据。T14 fixture 结果只证明机制，未用于本结论。

## 复现边界

按 [`person-state-acceptance.md`](../../../docs/person-state-acceptance.md) §3 使用授权
live 环境。运行必须保留完整自然章、真实 provider 和显式审核；不得加入 fixture
配置或自动提交 `same` / `supported` / `approve`。本目录不保存 env 文件、API key、
cookie、密码、主机路径或原始私密上传位置。
