---
task: C2-R3-T05
issue: 623
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T01, C2-R2-T05]
---

# 阶段评估、人物投影与快照分歧索引持久化

## 范围与交接

[Issue #623](https://github.com/6spot/Loom/issues/623) 给出实施步骤。在 Chronicle 产品库保存不可变评估与有界读取索引，为唯一发布事务提供可组合的存取接口。

- 输入：T01 DTO/键/上限；R2 reading_store、stream/unit/publication 关联；现有迁移和 transaction 约定。
- 交付：0008迁移、person_state_store.py及PG合同测试；提供 persist_person_state_assessments / persist_person_state_manifest / persist_person_state_disagreements / list_unit_people / list_unit_person_states / list_state_item_evidence，具体参数由T01类型固定；事务由调用方持有。
- 前置：[C2-R3-T01](https://github.com/6spot/Loom/issues/619)、[C2-R2-T05](https://github.com/6spot/Loom/issues/574)

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §6 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/persistence/migrations/0008_chronicle_person_states.sql（新，唯一 owner）`
- `apps/chronicle/persistence/person_state_store.py（新）`
- `apps/chronicle/persistence/test_person_state_store_postgres.py（新）`
- `apps/chronicle/docs/persistence.md`

可与 T02/T03/T04 并行。只写本轮新表和本 store；不改既有 migrations、canonical_store/worker。T08 在既有事务调用。

## 验收

- [ ] 新环境迁移成功，SQL只位于已注册persistence/migrations范围。
- [ ] 同输入幂等、不同payload冲突，FK/唯一约束阻止跨publication/stream/unit串线。
- [ ] 评估/状态/分歧可在同一外层事务回滚，读取保持有界且能翻到全部条目。
- [ ] 旧catalog与新catalog证据隔离，不覆盖immutable数据或使用LOOM_DATABASE_URL。

## 验证要求

```bash
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_person_state_store_postgres.py' -v
python3 tools/check_storage_sql_ownership.py
```

使用 docs/development/postgres-tests.md 的 PG18 服务与隔离 Chronicle 库；数据库测试不得因环境缺失被当作已通过。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
