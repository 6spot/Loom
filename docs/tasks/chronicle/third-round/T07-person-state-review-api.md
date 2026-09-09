---
task: C2-R3-T07
issue: 625
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T06, C2-R1-T09, C2-R1-T10]
---

# 混合审核队列、阶段依据详情与原文 API

## 范围与交接

[Issue #625](https://github.com/6spot/Loom/issues/625) 给出实施步骤。让现有连续审核界面能完整读到阶段依据和上下文，并通过同一decision路径提交评估。

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

## 验收

- [ ] 混合队列可遍历全部状态与身份项，过滤/游标/计数不串范围。
- [ ] 每个阶段候选能查看精确引用、前后文和整章，不能访问未授权成员锚点。
- [ ] decision按scope校验并复用T06，身份决定合同未被弱化。
- [ ] 所有读请求只读、无模型，错误不伪造成功或fallback至新revision。

## 验证要求

```bash
python3 -m unittest discover -s apps/chronicle/read_api -p 'test_person_state_review_api_unit.py' -v
python3 -m unittest discover -s apps/chronicle/read_api -p 'test_person_state_review_api_postgres.py' -v
python3 -m unittest discover -s apps/chronicle/read_api -p 'test_review_source_context_postgres.py' -v
```

PG使用当前开发指南；HTTP auth/路由边界由T10经Rust验证，本任务不绕开该入口让浏览器直连sidecar。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
