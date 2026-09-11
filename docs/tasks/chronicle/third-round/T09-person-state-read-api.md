---
task: C2-R3-T09
issue: 627
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T04, C2-R3-T05, C2-R2-T07, C2-R2-T08, C2-R2E-D02]
---

# 当前阅读片段的人物摘要、阶段详情与依据查询

## 范围与交接

[Issue #627](https://github.com/6spot/Loom/issues/627) 给出实施步骤。按固定综合版本及段落有界返回人物、地点的阶段资料，保持正文、状态和依据一致。原书阅读 unit 的扩展保持来源专用含义。

- 输入：T04已编译结果、T05索引；C2-R2E history API 的 version/paragraph/phase 和结论引用；原书专用分支才消费 R2 stream/unit/catalog。
- 交付：reading_people.py 的 dispatch_reading_people；people摘要与states/证据分页领域API及PG测试，不注册HTTP外层。
- 前置：[C2-R3-T04](https://github.com/6spot/Loom/issues/622)、[C2-R3-T05](https://github.com/6spot/Loom/issues/623)、[C2-R2-T07](https://github.com/6spot/Loom/issues/576)、[C2-R2-T08](https://github.com/6spot/Loom/issues/577)、[C2-R2E-D02](https://github.com/6spot/Loom/issues/660) 的 history 读取与结论引用合同；不要求整个 R2E 结束。

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §7 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/read_api/reading_people.py（新）`
- `apps/chronicle/read_api/test_reading_people_unit.py（新）`
- `apps/chronicle/read_api/test_reading_people_postgres.py（新）`

可与 T06/T07/T08 及前端模块并行。只消费store，路由/client由T10统一接线。

## 验收

- [ ] 同一locator得到稳定资料，人物集合与本段context一致，未来/结束项不被API重新加回。
- [ ] 综合主阅读复用 history API；不按同年、事件名或段落序号猜测来源 unit，人物详情与原段返回保持固定版本。
- [ ] 地点一项分别返回有据的行政归属和实际控制；到访、参战不自动推导控制。
- [ ] 分页可遍历所有人/身份/变化/依据，摘要省略显式可见，响应和查询都有界。
- [ ] 旧snapshot不混入后发布来源，分歧归属与anchor所属publication正确。
- [ ] 空资料、未知阶段和读取故障明确区分，所有GET无模型/写入/临时推断。

## 验证要求

```bash
python3 -m unittest discover -s apps/chronicle/read_api -p 'test_reading_people_unit.py' -v
python3 -m unittest discover -s apps/chronicle/read_api -p 'test_reading_people_postgres.py' -v
```

真实PG验证WHERE/索引/游标隔离；HTTP mock只能用于错误分支，不能替代快照成员检查。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
