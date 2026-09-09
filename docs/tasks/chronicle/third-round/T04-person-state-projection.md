---
task: C2-R3-T04
issue: 622
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T03]
---

# 按叙事阶段编译身份、变化与两档明确性

## 范围与交接

[Issue #622](https://github.com/6spot/Loom/issues/622) 给出实施步骤。用可测试的纯函数实现有效阶段与明确性判定，为发布/API/审核预览提供唯一运算规则。

- 输入：T03 remapped evidence、T01评估fixture、最终 canonical map、R2 reading manifest；已审核的来源分歧链接。
- 交付：person_state_projection.py；unit 人物状态/过程/空态和 catalog 分歧索引纯编译器及确定性 fixtures。
- 前置：[C2-R3-T03](https://github.com/6spot/Loom/issues/621)

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §§2–4、6 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/persistence/person_state_projection.py（新）`
- `apps/chronicle/persistence/test_person_state_projection_unit.py（新）`
- `apps/chronicle/persistence/test_person_state_disagreements_unit.py（新）`

可与 T05 和独立 UI 并行。T06/T08/T09 复用本模块，禁止各自实现“按年份猜状态”。

## 验收

- [ ] 有来源的同年阶段区分、兼任、针对性结束和再次任职均得到确定预期。
- [ ] 明确任命不被扩为永久在任；旧记载、完全无材料、未来、结束和阶段未知的结果不同。
- [ ] source/phase/assessment 的每个前提可在输出中追溯，未知/争议不被 confidence 或更新时间消除。
- [ ] 相同 unit 不因滚动路径改变；输出有界、排序/hash确定，无 DB/时钟/模型。

## 验证要求

```bash
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_person_state_projection_unit.py' -v
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_person_state_disagreements_unit.py' -v
```

这是本轮核心规则，必须逐条独立复核判定表与反例。测试预期从语料/契约推导，不能复制实现算法算 expected。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
