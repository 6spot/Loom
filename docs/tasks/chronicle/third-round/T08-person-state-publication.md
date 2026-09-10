---
task: C2-R3-T08
issue: 626
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T02, C2-R3-T04, C2-R3-T06, C2-R2-T06]
---

# 将阶段审核与人物投影接入唯一生产发布事务

## 范围与交接

[Issue #626](https://github.com/6spot/Loom/issues/626) 给出实施步骤。完整内容、阅读索引和人物阶段资料一次发布；中断、接管或审核未完不会公开半份结果。

- 输入：T02生产0.3、T03组装、T04编译、T05存储、T06评估；R2唯一worker/catalog lock/lease/stream发布路径。
- 交付：八阶段中resolve的两类审核接线及唯一publish事务扩展；故障/恢复PG整链测试。
- 前置：[C2-R3-T02](https://github.com/6spot/Loom/issues/620)、[C2-R3-T04](https://github.com/6spot/Loom/issues/622)、[C2-R3-T06](https://github.com/6spot/Loom/issues/624)、[C2-R2-T06](https://github.com/6spot/Loom/issues/575)

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §§4–6 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/worker/chapter_stage.py`
- `apps/chronicle/worker/production_worker.py（仅必要接线）`
- `apps/chronicle/worker/ingestion_worker.py（仅必要接线）`
- `apps/chronicle/persistence/resolve_publish.py`
- `apps/chronicle/persistence/chapter_store.py（仅0.3 accepted/发布版本接线）`
- `apps/chronicle/worker/test_person_state_pipeline_postgres.py（新）`
- `apps/chronicle/docs/worker.md`
- `apps/chronicle/docs/publication.md（人物投影接线引用）`

发布入口唯一owner。T07/T09在自己的领域文件可并行；不修改他们的SQL/helper或另建状态worker。

## 验收

- [ ] 正常生产经身份/阶段审核后公开完整正文与人物资料；无待审条目绕过发布。
- [ ] 各阶段故障/过期lease/接管不产生部分公开数据或重复模型调用。
- [ ] 同输入幂等，hash/映射/评估/catalog漂移被检测，不覆盖旧stream。
- [ ] 人物状态只用应用产品持久化，canonical union/负约束和既有job状态机不变。

## 验证要求

```bash
python3 -m unittest discover -s apps/chronicle/worker -p 'test_person_state_pipeline_postgres.py' -v
python3 -m unittest discover -s apps/chronicle/worker -p 'test_reading_pipeline_postgres.py' -v
python3 tools/check_architecture.py
```

必须独立复核事务/lease/冻结计划与故障注入结果；PG18测试不可用时如实记录，不能用纯fixture替代事务证明。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
