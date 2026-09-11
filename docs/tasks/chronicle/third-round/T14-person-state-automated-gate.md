---
task: C2-R3-T14
issue: 632
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T13, C2-R2-T16]
---

# 阶段资料整链、审核交互与阅读性能自动验收

## 范围与交接

[Issue #632](https://github.com/6spot/Loom/issues/632) 对应本任务；具体实施步骤、文件归属和验收要求保留在下文。用同一真实Rust/Python/PG生命周期和fixture模型覆盖第三轮整链与故障，接入当前CI。

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

## 整链终点必须是综合正文和人物页

下方来源上传／0.3／身份与阶段审核流程是输入准备，门禁还必须继续：

1. 通过正常 Studio API 显式选择发布来源，创建现有综合 job，执行 facts 审核、正文生成、prose／精选入口审核与发布。fixture 模式可使用固定操作者决定；live 必须保留实际逐项核对，不能套用这些自动决定。
2. 用真实 Rust/Python/PG 后端打开正式 HistoryPage 和独立人物页，记录 `version/paragraph_id/phase_id`、结论与原文锚点；source publication/stream/unit 只作来源证据。
3. 在综合正文中验证授任前后、兼任、针对性结束、任期不明／来源分歧，人物页状态与进入阶段一致，并能返回原段及段内偏移。读过精选事件后继续读已发布后文；人物状态变化不增加无关导航入口。
4. 混合队列实测身份、阶段依据、综合 facts、综合 prose 四种表单的分页／保存下一项／错误草稿；缺综合版本、只有 source stream、没有人物详情或缺返回场景必须失败。
5. 保存来源状态编译产物 → 综合核对结论 → 已发布段落状态的可核对关联，以及两次综合审核尚未完成时不发布的负例。只证明 JSON／source ReadingPage 或截图均不能代替这一闭环。

复用现有 gate_runtime 和生产入口；新增 case 与报告格式由本任务维护，不再创建独立部署或第二套 publication。

## 实施步骤

1. 复用现有 gate_runtime 管理隔离 Compose/PG/Studio/API/浏览器/清理；fixture 经正常上传、完整生成、来源身份／阶段审核及发布，再执行上方要求的显式综合任务与 facts/prose 两次审核，不直接写 DB 制造成功。
2. 扩展故障与负例矩阵：未审、错误主体、同年未知、兼任/结束/再任、来源冲突、future泄漏、版本漂移、失效lease、部分发布、重启adopt。
3. 浏览器验证阅读阶段切换/回溯/跨来源返回、两档与来源交互、混合连续审核/409/草稿、键盘/触屏/200%缩放及四种尺寸。
4. 按R2规模/环境测5次，已取得数据后侧栏p95≤100ms、无逐人N+1或≥200ms阅读主线程任务；保存环境、网络计数和结果，不临时放宽预算。
5. 在现有Chronicle workflow执行所需数据/浏览器gate，ci.yml只做必要路径路由/static检查；缺case/manifest/suite和清理失败必须显式失败。
6. 运行说明集中在person-state-acceptance.md；区分fixture机制证明与live内容判断，保证live不自动接受身份或阶段审核。

## 验收

- [ ] 真实栈fixture整链与故障通过，无直写DB、mock HTTP或跳过缺项冒充整链。
- [ ] 真实浏览器证明上下文/草稿/焦点/可读性与预算，保存可重查证据。
- [ ] CI覆盖第三轮路径，失败不被all/smoke聚合吞掉；门禁完整清理隔离资源。
- [ ] live入口复用同一流程、禁用fixture决定并保留人工核对会话。
- [ ] 门禁经两次综合审核发布真实 history 版本并验证正式历史／人物页、状态变化与原位返回；缺其中任一环节明确失败。

## 验证要求

```bash
python3 -m unittest discover -s apps/chronicle/acceptance -p 'test_third_round_gate.py' -v
python3 apps/chronicle/acceptance/third_round_gate.py --mode fixture --env-file /tmp/chronicle-r3-test.env --source-pack apps/chronicle/corpus/first-round/source-pack.json --evidence-dir /tmp/chronicle-r3-fixture
```

env文件按当前部署/验收指南准备隔离测试配置，不提交凭据。新增脚本由本任务创建；测试报告写真实candidate/manifest，不宣称尚未跑的live结果。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
