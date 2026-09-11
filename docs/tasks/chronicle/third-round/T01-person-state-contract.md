---
task: C2-R3-T01
issue: 619
kind: leaf
parent: C2-R3
depends_on: [C2-R3-D01, C2-R3-D02, C2-R2-T01, C2-R2-T02, C2-R2E-D02]
---

# 0.3 阶段资料 schema、校验器与前后端共享类型

## 范围与交接

[Issue #619](https://github.com/6spot/Loom/issues/619) 对应本任务；具体实施步骤、文件归属和验收要求保留在下文。把阶段/事实/审核/公开读取约定变成各模块可直接消费的机器契约，避免 Luna 在实现中自定状态语义。

- 输入：D01 cases；R2 的 0.2 candidate/artifact 与组件 scene/runner；C2-R2E `source-corroboration.md`、`narrative_contract.py` 和 `narrative-types.ts` 的已审核结论及综合位置。
- 交付：0.3 candidate/artifact schemas、person-state schema、person_state_contract.py、person-state-types.ts、正反例；纯函数与审核/读取 DTO 固定，浏览器基座注册第三轮独立 suite。
- 前置：[C2-R3-D01](https://github.com/6spot/Loom/issues/617)、[C2-R3-D02](https://github.com/6spot/Loom/issues/618) 的共用 harness 场景交接、[C2-R2-T01](https://github.com/6spot/Loom/issues/570)、[C2-R2-T02](https://github.com/6spot/Loom/issues/571)、[C2-R2E-D02](https://github.com/6spot/Loom/issues/660) 的结论、综合位置及明确性合同；不要求整个 R2E 结束。

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §§2–7 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

主阅读使用 `{version, paragraph_id, phase_id}`，原 `{stream_id, unit_id}` 仅用于来源阅读。统一 `certainty=clear|uncertain`，状态最终落入共用结论的 office/title/allegiance/administration/control 维度；不能另建 `unclear` 真伪枚举。0.3 来源候选属于任期推理输入，不直接变成已审核历史结论。结论事实、内部阶段与精选导航入口分开，原始 Event 不自动成为锚点。

## 文件归属

- `apps/chronicle/ingestion/schemas/chronicle-chapter-candidate-v0.3.schema.json（新）`
- `apps/chronicle/ingestion/schemas/chronicle-chapter-artifact-v0.3.schema.json（新）`
- `apps/chronicle/ingestion/schemas/chronicle-person-state-v0.1.schema.json（新）`
- `apps/chronicle/persistence/person_state_contract.py（新）`
- `apps/chronicle/docs/person-state-reading.md（同步综合交接、审核范围与冻结版本合同；在下游开工前完成）`
- `apps/chronicle/persistence/test_person_state_contract_unit.py（新）`
- `apps/chronicle/ingestion/fixtures/c2r3-contract/**（新）`
- `apps/chronicle/webapp/src/lib/person-state-types.ts（新）`
- `apps/chronicle/webapp/tests/person-state-types.test.ts（新）`
- `apps/chronicle/webapp/scripts/reading-component-smoke.mjs（仅第三轮 suite 注册）`
- `apps/chronicle/webapp/tests/fixtures/reading/scenes/person-state-harness/**（新）`
- `apps/chronicle/webapp/tests/reading-browser/person-state-harness.mjs（新）`

完成后 T02/T03/T05/T11/T12 可按各自其他前置并行。共用 harness 场景在 D02 后串行接手，保留既有交互证据；共享 schema/types/runner 只由本任务修改；后续新增字段回此契约统一处理。新 production 版本注册交给 T02。

## 本任务必须先锁定的 R2E 交接

1. 定义来源阶段证据／评估／编译结果供综合事实核对消费的机器输入：保留 source publication、原章 local refs、canonical 人物、Claim／anchor、适用依据、限定语及输入 hashes。综合 phase 与来源 phase 是不同空间；有明确关联才使用，没有关联时保留未知或交回核对，禁止按年份／事件名／段落号猜测。
2. 固定 #622 输出、#626 生产接线、#627 只读查询使用的同一份 JSON fixture。来源的 supported 只评价该证据，不能绕过现有 facts/prose 审核变成公开的 clear 结论；综合状态最终来自固定 publication version 的已审核结论。
3. 核对当前 `studio_reviews.py` 和 `studio-api.ts` 已支持的 `resolution | narrative`。同步人物契约 §5.1 中旧的默认范围描述，使未显式筛选的当前审核入口继续包含综合 facts/prose；明确 `review_scope=all` 覆盖 resolution、person_state、narrative。候选类型、草稿键、cursor、计数与决定 payload 均保留 scope，不能把 narrative 当身份决定或状态评估提交。
4. 在本任务中先更新 canonical 契约的相应条款和共享 fixtures；#625/#628/#631 消费已固定合同，不各自决定默认范围。共享接口与产品契约未收敛时，不开放依赖它们的实现任务。

验收增加：同一源事实经交接仍能追到原文；错误／缺失阶段关联不得产生当前身份；综合审核的省略参数入口、all 与各明确筛选范围均有一致的期望。该节点只固定合同，不代替 #626 的生产接线或 #632/#633 的整链验证。

## 实施步骤

1. 在 0.2 上增加 person_states，复用基础原文选择器、reading 与 C0 引用校验，不复制一套章节解码或身份规则。
2. 固定 phases/orders/unit_phases/facts/continuities/disagreements 的字段、枚举、上限、local ID 类型；定义无材料、未知阶段、拒绝资料与不明确项的不同 DTO。
3. 实现 schema/ref/type/phase DAG/unit 一对一/原文及 reading 相容性校验；拒绝模型填写 supported、certainty、canonical ID 或 URL。
4. 固定审核候选键、assessment overlay、plan fingerprint 输入、状态键、半开有效区间、disagreement index 与公共摘要/详情/evidence 分页的类型和排序；共享结论与综合位置复用 #660，来源 unit 与综合段落的 DTO 分开，提供 Python/TS 对照 JSON fixture。
5. 覆盖父祖主体、未来、已结束、再次任命、推荐/追赠、自称/引述、未知任期、同年不可比等最小反例；校验器只检查可程序证明的条件。
6. 在现有 browser runner 注册 r3-harness/person-states/person-state-review/r3-all；保留第二轮 suite，r3-all 缺任一组件 spec 必须失败。后续组件只写自己的 scene/spec。

## 验收

- [ ] 0.3 有效联合章通过，缺阅读/译文/来源或跨章悬空引用、phase 环、错主体类型均失败。
- [ ] 模型不能直接生产最终明确性/评估/UUID；confidence 不参与显示判定。
- [ ] Python 与 TS 消费同一批审核及公开 DTO，游标/上限/空态/限定语没有未定义分支。
- [ ] 新历史位置与原来源位置不可混用；结论及状态绑定相同 publication version，地点行政归属与实际控制分开。
- [ ] r3-harness 实际浏览器通过，r3-all 对缺失 suite 失败；未接生产 worker/App。
- [ ] 来源推理结果与综合核对输入有共同 fixture、明确阶段关联和原文归属；队列默认范围/all 保留 narrative，canonical 条款已同步后才交给下游。
- [ ] 综合 position/version、来源 unit/publication 不可串型；逐项使用 clear/uncertain，行政归属与实际控制分开，原始 Event 不自动成为锚点。

## 验证要求

```bash
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_person_state_contract_unit.py' -v
npm --prefix apps/chronicle/webapp test -- tests/person-state-types.test.ts
node apps/chronicle/webapp/scripts/reading-component-smoke.mjs --base-url http://127.0.0.1:5173 --suite r3-harness --output /tmp/chronicle-r3-contract-browser
```

浏览器使用现有 Vite 开发入口。结构通过不等于语义正确；schema 与显示判定表需独立复核一次，不能把未定义产品问题留给后续各组件自行决定。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
