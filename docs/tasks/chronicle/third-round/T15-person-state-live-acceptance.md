---
task: C2-R3-T15
issue: 633
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T14, C2-R2-T17]
---

# 真实整章人物阶段资料与阅读体验独立验收

## 范围与交接

[Issue #633](https://github.com/6spot/Loom/issues/633) 给出实施步骤。在全新环境使用真实模型和人工审核，逐案验证人物、时间、依据与阅读展示确实一致，而非只有fixture通过。

- 输入：D01完整原件/16案、D02设计、T14运行指南与live gate、实际前两轮内容验收结果。
- 交付：第三轮独立验收报告、去敏manifest、逐案publication/unit/source证据与截图/失败分类；保留真实未通过项。
- 前置：[C2-R3-T14](https://github.com/6spot/Loom/issues/632)、[C2-R2-T17](https://github.com/6spot/Loom/issues/586)

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §9 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/corpus/third-round/acceptance/**（新，本次运行证据）`
- `apps/chronicle/docs/person-state-acceptance.md（实际结果索引/限制）`

依赖真实整链就绪后串行最终验收。产品修复交对应owner，不在验收任务里悄悄修改算法或重写gold预期。

## 验收

- [ ] 真实provider及两类人工审核/发布流程完成，16案均有可复查逐案结论和来源。
- [ ] 明确/不明确标记对应实际证据与阶段，无未来头衔、父祖误归属、角色永久化或未知被补全。
- [ ] 阅读、接口、投影版本一致，真实手机/键盘与返回行为有证据。
- [ ] 报告如实保留失败/未验证及修复归属；未通过时不能宣称第三轮功能验收完成。

## 验证要求

```bash
python3 apps/chronicle/acceptance/third_round_gate.py --mode live --env-file /tmp/chronicle-r3-live.env --source-pack apps/chronicle/corpus/first-round/source-pack.json --evidence-dir /tmp/chronicle-r3-live
git diff --check
```

模型调用需要可用的真实测试配置，缺失则记录具体缺口；人工决定由实际审核操作者作出，不自动代替。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
