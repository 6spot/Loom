---
task: C2-R3-T04
issue: 622
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T03]
---

# 按叙事阶段编译身份、变化与两档明确性

## 范围与交接

[Issue #622](https://github.com/6spot/Loom/issues/622) 对应本任务；具体实施步骤、文件归属和验收要求保留在下文。用可测试的纯函数实现有效阶段与明确性判定，为发布/API/审核预览提供唯一运算规则。

- 输入：T03 remapped evidence、T01评估fixture、最终 canonical map、R2 reading manifest；已审核的来源分歧链接。
- 交付：person_state_projection.py；来源 unit 人物状态／过程／空态和 catalog 分歧索引纯编译器；带原始依据和评估归属的综合核对输入及确定性 fixtures。
- 前置：[C2-R3-T03](https://github.com/6spot/Loom/issues/621)

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §§2–4、6 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/persistence/person_state_projection.py（新）`
- `apps/chronicle/persistence/test_person_state_projection_unit.py（新）`
- `apps/chronicle/persistence/test_person_state_disagreements_unit.py（新）`

可与 T05 和独立 UI 并行。T06/T08/T09 复用本模块，禁止各自实现“按年份猜状态”。

## 综合事实核对的输出交接

本任务的 unit 投影继续用于来源阅读，同时按 #619 固定的 DTO 输出供 #626 消费的阶段证据／推理结果。每条保留来源 publication、章内事实／阶段、Claim／anchor、评估及持续／结束依据，不能只交一串展示文字。

这些结果是综合事实核对的输入，不直接变为已审核综合结论。无有据的来源阶段与综合阶段关联时，不伪造映射；综合版的 clear/uncertain 与适用阶段仍由现有审核链固定。原始 Event、任免或内部 phase 不自动生成 entry_points。

验收增加：带同年未知先后、明确结束、兼任及来源分歧的输出可被共用 fixture 消费；仅有 supported 授任不得生成无限期的明确在任。保留本任务纯函数边界，模型／DB／发布由其他 owner 接线。

## 实施步骤

1. 只用 supported 阶段绑定/先后边及现有可比较日期形成偏序；同年、同事件、正文顺序不产生隐含先后。
2. 实现 office/title/affiliation 的状态键、start/end/attest、明确持续区间及限定语；结束只影响相同键且已证明在先的记录，允许重新任职与兼任。 值/政权的显示标签使用该阶段的来源表示，不回填后来国号。
3. 按契约判定表编译 clear/unclear/reasons：以前任职但任期未知可弱化，未来/已结束不进入当前，完全无材料为空态；confidence 不参与。
4. 处理 single/process/ambiguous/unknown：process 显示各阶段，不能取末态替代整段；unknown 不沿用上一段，回读相同 unit 直接得到同一结果。
5. 编译明确记录的来源分歧与 catalog membership绑定，保留两方证据；不同官职或同年不同阶段不自动视为冲突，后续索引只能增加有依据的不明确原因。
6. 用 D01/T01 反例检验祖辈误归属、推荐/自称/追赠、引述结束、跨章同人/未解身份、终止后再授、前后读序、循环和不一致输入。

## 验收

- [ ] 有来源的同年阶段区分、兼任、针对性结束和再次任职均得到确定预期。
- [ ] 明确任命不被扩为永久在任；旧记载、完全无材料、未来、结束和阶段未知的结果不同。
- [ ] source/phase/assessment 的每个前提可在输出中追溯，未知/争议不被 confidence 或更新时间消除。
- [ ] 相同 unit 不因滚动路径改变；输出有界、排序/hash确定，无 DB/时钟/模型。
- [ ] #626 可消费带来源与阶段依据的编译输出；没有映射或未经综合核对的结果不能直接成为主阅读的已审核状态。

## 验证要求

```bash
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_person_state_projection_unit.py' -v
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_person_state_disagreements_unit.py' -v
```

这是本轮核心规则，必须逐条独立复核判定表与反例。测试预期从语料/契约推导，不能复制实现算法算 expected。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
