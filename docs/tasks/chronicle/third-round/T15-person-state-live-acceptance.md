---
task: C2-R3-T15
issue: 633
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T14, C2-R2-T17]
---

# 真实整章人物阶段资料与阅读体验独立验收

## 范围与交接

[Issue #633](https://github.com/6spot/Loom/issues/633) 对应本任务；具体实施步骤、文件归属和验收要求保留在下文。在全新环境使用真实模型和人工审核，逐案验证人物、时间、依据与阅读展示确实一致，而非只有fixture通过。

- 输入：D01完整原件/16案、D02设计、T14运行指南与live gate、实际前两轮内容验收结果。
- 交付：第三轮独立验收报告、去敏 manifest、逐案综合 version/paragraph/phase 及来源 publication/unit/anchor 证据、截图／失败分类；保留真实未通过项。
- 前置：[C2-R3-T14](https://github.com/6spot/Loom/issues/632)、[C2-R2-T17](https://github.com/6spot/Loom/issues/586)

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §9 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/corpus/third-round/acceptance/**（新，本次运行证据）`
- `apps/chronicle/docs/person-state-acceptance.md（实际结果索引/限制）`

依赖真实整链就绪后串行最终验收。产品修复交对应owner，不在验收任务里悄悄修改算法或重写gold预期。

## 真实验收必须覆盖最终产品

完成来源 0.3、身份与阶段依据审核／发布后，还须通过既有显式综合任务，实际核对 facts，生成正文，再核对正文与精选入口，最后发布。沿用真实 provider 和人工审核；来源审核通过不代表综合结论已核准。

- 对 D01 案例逐项记录来源事实／阶段、评估／manifest 与最终综合结论的对应，最终页面证据包含 `version/paragraph_id/phase_id`、人物页进入阶段、原文 publication/anchor。某案没有进入综合版本时应标未覆盖及原因，不能用来源侧结果代替。
- 在正式 HistoryPage 与独立人物页实测授任前后、兼任、针对性离任、再次任命、未知任期和分歧；进入人物页及返回原段／段内偏移、刷新／回退都保持版本和阶段。缺真实样本的反例仍按 D01 标明 synthetic，不冒称真实史料证明。
- 事实/正文两项综合审核都有实际操作者及最终内容记录；四类混合审核的页底连续操作、手机和键盘均有证据。锚点仍是少量重要事件／时期，阅读可继续经过事件后续。
- 报告区分来源生成与来源审核、综合事实审核、正文审核、最终读取和体验各层结果。只有 source publication/stream/unit、fixture PASS、页面截图或 CI 通过均不足以宣布 R3 验收完成。

既有完整原件足够开始，不要求用户另行补传资料。本文只补齐已确认的综合历史链路与人物页验收，不扩大到跨批次无限历史或背景图管理。

## 实施步骤

1. 按canonical指南启动新隔离环境，预检provider容量与凭据；使用第一轮完整自然章source pack，不以节选替代。
2. 经 Studio 上传、0.3 联合生成、身份审查、按章阶段依据审查及来源发布，再显式创建综合任务并完成事实／正文两次审核与发布；真实人工决定，不套 fixture 的自动 same/supported/approve。
3. 至少核对D01的16案，逐项记录原文/引述归属、人物与值/对象、phase/Claim/anchor、当时身份/变化和明确性；记录模型遗漏及错误，不只查字段存在。
4. 在实际阅读页走兼任、转投、同年阶段、回溯/返回/刷新、source disagreement和暂无材料，核对前端/API/发布投影同一版本；手机/键盘实际操作。
5. 记录candidate commit、provider/run、publication/stream/catalog/manifest、未验证项、截图与各案PASS/FAIL/BLOCKED；去除token/cookie/password/上传私密文件路径。
6. 失败明确归属抽取/契约/阶段/审核/发布/API/UI，不把关闭Issue或离线PASS当实际通过；汇总交付范围与真实限制。

## 验收

- [ ] 真实 provider、来源审核及综合事实／正文审核发布完成；至少16案逐条列出结果和证据，真实案与 synthetic 反例分开标记，未覆盖不得计为通过。
- [ ] 明确/不明确标记对应实际证据与阶段，无未来头衔、父祖误归属、角色永久化或未知被补全。
- [ ] 阅读、接口、投影版本一致，真实手机/键盘与返回行为有证据。
- [ ] 报告如实保留失败/未验证及修复归属；未通过时不能宣称第三轮功能验收完成。
- [ ] 真实综合事实及正文审核均完成，案例结果有固定综合位置、人物页和原文对应证据；仅 source stream 或 synthetic 的结果明确标出。

## 验证要求

```bash
python3 apps/chronicle/acceptance/third_round_gate.py --mode live --env-file /tmp/chronicle-r3-live.env --source-pack apps/chronicle/corpus/first-round/source-pack.json --evidence-dir /tmp/chronicle-r3-live
git diff --check
```

模型调用需要可用的真实测试配置，缺失则记录具体缺口；人工决定由实际审核操作者作出，不自动代替。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
