---
task: C2-R3-T14
issue: 632
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T13, C2-R2-T16]
---

# 阶段资料整链、审核交互与阅读性能自动验收

## 范围与交接

[Issue #632](https://github.com/6spot/Loom/issues/632) 给出实施步骤。用同一真实Rust/Python/PG生命周期和fixture模型覆盖第三轮整链与故障，接入当前CI。

- 输入：T13生产集成；R2 gate_runtime/reading浏览器验收；D01/T01固定正反例；现有CI workflows。
- 交付：thin third_round_gate.py、第三轮浏览器场景/driver、CI接线与唯一person-state-acceptance运行指南。
- 前置：[C2-R3-T13](https://github.com/6spot/Loom/issues/631)、[C2-R2-T16](https://github.com/6spot/Loom/issues/585)

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §9 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/acceptance/third_round_gate.py（新，薄入口）`
- `apps/chronicle/acceptance/test_third_round_gate.py（新）`
- `apps/chronicle/acceptance/gate_runtime.py（仅共享生命周期扩展）`
- `apps/chronicle/webapp/scripts/person-state-flow-smoke.mjs（新，复用阅读driver支持）`
- `apps/chronicle/webapp/tests/reading-browser/integration/person-states/**（新）`
- `apps/chronicle/docs/person-state-acceptance.md（新，唯一运行说明）`
- `.github/workflows/chronicle.yml`
- `.github/workflows/ci.yml`

接线后串行验收；不同时修改产品实现或放宽阈值。失败交回对应模块修复后再验证相关门。

## 验收

- [ ] 真实栈fixture整链与故障通过，无直写DB、mock HTTP或跳过缺项冒充整链。
- [ ] 真实浏览器证明上下文/草稿/焦点/可读性与预算，保存可重查证据。
- [ ] CI覆盖第三轮路径，失败不被all/smoke聚合吞掉；门禁完整清理隔离资源。
- [ ] live入口复用同一流程、禁用fixture决定并保留人工核对会话。

## 验证要求

```bash
python3 -m unittest discover -s apps/chronicle/acceptance -p 'test_third_round_gate.py' -v
python3 apps/chronicle/acceptance/third_round_gate.py --mode fixture --env-file /tmp/chronicle-r3-test.env --source-pack apps/chronicle/corpus/first-round/source-pack.json --evidence-dir /tmp/chronicle-r3-fixture
```

env文件按当前部署/验收指南准备隔离测试配置，不提交凭据。新增脚本由本任务创建；测试报告写真实candidate/manifest，不宣称尚未跑的live结果。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
