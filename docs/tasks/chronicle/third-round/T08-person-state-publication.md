---
task: C2-R3-T08
issue: 626
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T02, C2-R3-T04, C2-R3-T06, C2-R2-T06]
---

# 将阶段审核与人物投影接入唯一生产发布事务

## 范围与交接

[Issue #626](https://github.com/6spot/Loom/issues/626) 对应本任务；具体实施步骤、文件归属和验收要求保留在下文。完整内容、阅读索引和人物阶段资料一次发布；中断、接管或审核未完不会公开半份结果。

- 输入：T02生产0.3、T03组装、T04编译、T05存储、T06评估；R2唯一worker/catalog lock/lease/stream发布路径。
- 交付：来源 resolve 的身份／阶段审核及原子发布扩展；阶段依据接入既有显式综合任务，经 facts/prose 两次审核形成固定版本；故障／恢复 PG 整链测试。
- 前置：[C2-R3-T02](https://github.com/6spot/Loom/issues/620)、[C2-R3-T04](https://github.com/6spot/Loom/issues/622)、[C2-R3-T06](https://github.com/6spot/Loom/issues/624)、[C2-R2-T06](https://github.com/6spot/Loom/issues/575)

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §§4–6 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/worker/chapter_stage.py`
- `apps/chronicle/worker/production_worker.py（仅必要接线）`
- `apps/chronicle/worker/ingestion_worker.py（仅必要接线）`
- `apps/chronicle/persistence/resolve_publish.py`
- `apps/chronicle/persistence/chapter_store.py（仅0.3 accepted/发布版本接线）`
- `apps/chronicle/worker/narrative_stage.py（已有综合任务接入冻结的人物阶段依据）`
- `apps/chronicle/persistence/narrative_store.py（综合上下文与已审核发布的接线；SQL仍限持久化边界）`
- `apps/chronicle/persistence/narrative_contract.py（#619合同固定后，仅必要的共用输入适配，不另定事实语义）`
- `apps/chronicle/worker/test_narrative_pipeline_postgres.py（现有综合链路的状态输入与双审核回归）`
- `apps/chronicle/worker/test_person_state_pipeline_postgres.py（新）`
- `apps/chronicle/docs/worker.md`
- `apps/chronicle/docs/publication.md（人物投影接线引用）`

发布入口唯一owner。T07/T09在自己的领域文件可并行；不修改他们的SQL/helper或另建状态worker。

## 必须同时交付的综合历史接线

下方原有步骤覆盖来源 0.3 的审核／发布。本任务还负责把 #622 的有据阶段结果经 #619 的共同输入交给现有综合生产链，否则第三轮状态算法仍未接入主阅读。

1. 来源发布后，继续由操作员显式选择完整已发布章节创建既有综合 job；不因导入自动重写历史。冻结所选来源的状态 manifest／assessment／compiler 等输入及其 hash，恢复续用同一份，不临时读取最新状态。
2. 把可追溯结果作为现有综合 facts 核对的输入，保留完整章节、原始归属、状态限定和阶段依据。来源 phase 与综合 phase 按共享合同校验；不得根据同年或事件名推定等价。
3. 综合 facts 中的状态结论仍经逐项审核；通过后生成正文，正文及精选入口再审核，最后走既有 narrative publication 事务。来源 supported、身份已合并、来源章节已发布均不能替代这两次审核。
4. 正式 history 读取的状态必须属于其 publication version、paragraph 和 phase，并能回查相同版本的已审核结论及来源。不得在 GET 时叠加最新来源投影或再次运行推理。
5. PG 整链证明：来源发布本身不公开新综合正文；事实或正文未审不能公开；最终发布一次可见正文／状态／依据，重启和重放不改旧版，也不重复生成。另有来源状态 manifest 漂移与错误阶段关联的失败例。

来源发布与显式综合发布各复用自己的既有事务边界，不把它们合成一条持有人审或模型等待的长事务。共享字段由 #619 固定；本任务是上述生产接线文件的 owner，#625/#627 不并行改写这些文件。

## 实施步骤

1. resolve先沿用身份审查，终态后冻结/恢复状态依据包；现有job/resolve继续needs_review，直到本job全部种类open reviews处理完。
2. accepted run恢复重验整份0.3、source/plan/config fingerprint；保留已完成身份决定和状态评估，禁止为接管再生成状态。
3. 调用T03/T04一次编译并记录版本/hash；publication前固定最终映射与审核base，检测漂移/新增相关冲突为stale，不隐式放行。
4. 在既有advisory lock与lease-fenced短事务中写catalog、全部章、reading索引、state manifest/index、catalog分歧索引与checkpoint；编译/模型/人工等待在事务外。
5. 注入在canonical、chapter、reading、state、checkpoint各处的失败；检查对外全无或完整可见，相同输入重试返回原publication/stream。
6. 来源 job 的 present 核对已发布译文／资料；显式综合 job 的 present 沿用已有事实核对、正文审核与发布流程。来源缺0.3、未审、混版或hash不符明确失败；保留R1/R2局部回归。

## 验收

- [ ] 正常生产经身份/阶段审核后公开完整正文与人物资料；无待审条目绕过发布。
- [ ] 各阶段故障/过期lease/接管不产生部分公开数据或重复模型调用。
- [ ] 同输入幂等，hash/映射/评估/catalog漂移被检测，不覆盖旧stream。
- [ ] 人物状态只用应用产品持久化，canonical union/负约束和既有job状态机不变。
- [ ] 0.3 阶段依据已进入正常综合核对，facts/prose 两次审核后主历史的正文、人物状态与引用属于同一固定版本；只有来源发布成功不算完成。

## 验证要求

```bash
python3 -m unittest discover -s apps/chronicle/worker -p 'test_person_state_pipeline_postgres.py' -v
python3 -m unittest discover -s apps/chronicle/worker -p 'test_reading_pipeline_postgres.py' -v
python3 tools/check_architecture.py
```

必须独立复核事务/lease/冻结计划与故障注入结果；PG18测试不可用时如实记录，不能用纯fixture替代事务证明。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
