---
task: C2-R3-T06
issue: 624
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T04, C2-R3-T05, C2-R1-T08]
---

# 按章冻结阶段依据审核与评估产物

## 范围与交接

[Issue #624](https://github.com/6spot/Loom/issues/624) 给出实施步骤。在已有身份审核之后按章集中核对阶段依据，记录明确/不明确所需的评估而不改变人物合并权威。

- 输入：T03 evidence、T04 compiler预览、T05 store；已完成的Resolution决定及其hash、base catalog、现有ReviewItem/job lock。
- 交付：person_state_review.py：build_person_state_review_plan / open_person_state_reviews / resolve_person_state_review / collect_person_state_assessments；每章候选完整覆盖的不可变plan和assessment artifact。
- 前置：[C2-R3-T04](https://github.com/6spot/Loom/issues/622)、[C2-R3-T05](https://github.com/6spot/Loom/issues/623)、[C2-R1-T08](https://github.com/6spot/Loom/issues/558)

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §§2、5–6 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/persistence/person_state_review.py（新）`
- `apps/chronicle/persistence/test_person_state_review_unit.py（新）`
- `apps/chronicle/persistence/test_person_state_review_postgres.py（新）`

T07 接审核DTO/API，T08 接worker，本任务不抢写他们的入口。可与 T09/独立 UI 并行。

## 验收

- [ ] 每章一份依据包、每候选恰好一次，恢复不重复造审核债务。
- [ ] supported/uncertain/disputed/rejected及默认/例外作用域精确，未审/跳过不自动通过。
- [ ] 评估不会产生same_entity或覆盖原始artifact；授任评估与后续任期适用性分开。
- [ ] 并发/409/重复提交/plan漂移均有PG证据，保存原子且审计可追。

## 验证要求

```bash
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_person_state_review_unit.py' -v
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_person_state_review_postgres.py' -v
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_review_subjects_chapter_unit.py' -v
```

独立复核frozen候选覆盖与事务边界；保留Amendment0007身份批次/逐组例外全部既有约束。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
