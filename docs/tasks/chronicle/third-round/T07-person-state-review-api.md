---
task: C2-R3-T07
issue: 625
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T06, C2-R1-T09, C2-R1-T10]
---

# 混合审核队列、阶段依据详情与原文 API

## 范围与交接

[Issue #625](https://github.com/6spot/Loom/issues/625) 对应本任务；具体实施步骤、文件归属和验收要求保留在下文。让现有连续审核界面能完整读到阶段依据和上下文，并通过同一decision路径提交评估。

- 输入：T06 frozen plan/decision接口；R1 studio_reviews.py与source_context；T01判别联合DTO。
- 交付：studio_person_states.py 的 dispatch_person_state_review 及现有审核dispatcher扩展；有review_scope的有界混合队列和版本化详情/上下文/决定。
- 前置：[C2-R3-T06](https://github.com/6spot/Loom/issues/624)、[C2-R1-T09](https://github.com/6spot/Loom/issues/559)、[C2-R1-T10](https://github.com/6spot/Loom/issues/560)

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §5.1 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/read_api/studio_person_states.py（新）`
- `apps/chronicle/read_api/studio_reviews.py（本轮领域队列 owner）`
- `apps/chronicle/read_api/test_person_state_review_api_unit.py（新）`
- `apps/chronicle/read_api/test_person_state_review_api_postgres.py（新）`
- `apps/chronicle/docs/review-workflow.md（实施接口说明）`

可与 T08/T09 和独立 UI 并行。Python顶层router、Rust、typed client交T10；本任务复用source_context，不另建原文服务。

## 保留当前综合审核的接线要求

当前 main 的队列已经包含 `scope=narrative`，其 `narrative_kind=facts|prose` 通过既有 `narrative_store` 核对和保存。本任务消费 #619 同步后的混合队列合同：all 必须包含 resolution、person_state、narrative，默认入口不得因扩展而遗漏现有综合审核。

新增 person_state 的列表／详情／contexts／decision 分派时保留 narrative 分支，不能把它路由到 Resolution 或阶段 assessment。不同 scope 的 payload 串用必须失败；分页、open_count、cursor 和下一项遍历覆盖整个所选范围。综合事实批准继续校验每条 reviewed_conclusion_ids，正文批准继续绑定其候选及来源版本。

验收增加：用同一队列中的身份项、阶段依据项、综合事实项、综合正文项验证遍历与类型分派，保留原有综合审核／恢复的回归；不能只用前两类记录证明混合队列完整。

## 实施步骤

1. 现有列表按 #619 已同步的合同增加 review_scope 与默认行为；all 包含 resolution/person_state/narrative，默认入口保留综合审核。link_kind 的合法范围与拒绝规则消费同一合同，cursor/open_count 绑定完整 scope。
2. 按frozen payload.scope分派详情/decision，返回可读人物/章/变化摘要；拒绝用same_entity字段提交阶段评估或反向串用。
3. contexts支持candidate_id和有界分页，覆盖整包全部来源；原文window/chapter读取校验本包成员、artifact/source hash及外部base catalog成员。
4. 引用无直接Claim的阶段支持仍通过精确source selections显示，不把人物合并的首条引用替代阶段依据；引述/注释单独标注。
5. 保留400/404/409错误语义、服务端稿件终态核对、全scope待审计数和再扫描所需数据；测试混合分页、并发与源文件缺失/漂移。

## 验收

- [ ] 混合队列可遍历全部状态与身份项，过滤/游标/计数不串范围。
- [ ] 每个阶段候选能查看精确引用、前后文和整章，不能访问未授权成员锚点。
- [ ] decision按scope校验并复用T06，身份决定合同未被弱化。
- [ ] 所有读请求只读、无模型，错误不伪造成功或fallback至新revision。
- [ ] 身份、阶段依据、综合事实、综合正文四类实际审核均可完整遍历和正确提交，旧 narrative 决定与逐项覆盖校验保留。

## 验证要求

```bash
python3 -m unittest discover -s apps/chronicle/read_api -p 'test_person_state_review_api_unit.py' -v
python3 -m unittest discover -s apps/chronicle/read_api -p 'test_person_state_review_api_postgres.py' -v
python3 -m unittest discover -s apps/chronicle/read_api -p 'test_review_source_context_postgres.py' -v
```

PG使用当前开发指南；HTTP auth/路由边界由T10经Rust验证，本任务不绕开该入口让浏览器直连sidecar。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
