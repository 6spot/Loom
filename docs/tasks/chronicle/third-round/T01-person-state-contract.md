---
task: C2-R3-T01
issue: 619
kind: leaf
parent: C2-R3
depends_on: [C2-R3-D01, C2-R2-T01, C2-R2-T02]
---

# 0.3 阶段资料 schema、校验器与前后端共享类型

## 范围与交接

[Issue #619](https://github.com/6spot/Loom/issues/619) 给出实施步骤。把阶段/事实/审核/公开读取约定变成各模块可直接消费的机器契约，避免 Luna 在实现中自定状态语义。

- 输入：D01 cases；R2-T01 的 0.2 candidate/artifact、reading_contract.py、reading-types.ts；R2-T02 的独立组件 scene/runner。
- 交付：0.3 candidate/artifact schemas、person-state schema、person_state_contract.py、person-state-types.ts、正反例；纯函数与审核/读取 DTO 固定，浏览器基座注册第三轮独立 suite。
- 前置：[C2-R3-D01](https://github.com/6spot/Loom/issues/617)、[C2-R2-T01](https://github.com/6spot/Loom/issues/570)、[C2-R2-T02](https://github.com/6spot/Loom/issues/571)

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §§2–7 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/ingestion/schemas/chronicle-chapter-candidate-v0.3.schema.json（新）`
- `apps/chronicle/ingestion/schemas/chronicle-chapter-artifact-v0.3.schema.json（新）`
- `apps/chronicle/ingestion/schemas/chronicle-person-state-v0.1.schema.json（新）`
- `apps/chronicle/persistence/person_state_contract.py（新）`
- `apps/chronicle/persistence/test_person_state_contract_unit.py（新）`
- `apps/chronicle/ingestion/fixtures/c2r3-contract/**（新）`
- `apps/chronicle/webapp/src/lib/person-state-types.ts（新）`
- `apps/chronicle/webapp/tests/person-state-types.test.ts（新）`
- `apps/chronicle/webapp/scripts/reading-component-smoke.mjs（仅第三轮 suite 注册）`
- `apps/chronicle/webapp/tests/fixtures/reading/scenes/person-state-harness/**（新）`
- `apps/chronicle/webapp/tests/reading-browser/person-state-harness.mjs（新）`

完成后 T02/T03/T05/T11/T12 可按各自其他前置并行。共享 schema/types/runner 只由本任务修改；后续新增字段回此契约统一处理。新 production 版本注册交给 T02。

## 验收

- [ ] 0.3 有效联合章通过，缺阅读/译文/来源或跨章悬空引用、phase 环、错主体类型均失败。
- [ ] 模型不能直接生产最终明确性/评估/UUID；confidence 不参与显示判定。
- [ ] Python 与 TS 消费同一批审核及公开 DTO，游标/上限/空态/限定语没有未定义分支。
- [ ] r3-harness 实际浏览器通过，r3-all 对缺失 suite 失败；未接生产 worker/App。

## 验证要求

```bash
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_person_state_contract_unit.py' -v
npm --prefix apps/chronicle/webapp test -- tests/person-state-types.test.ts
node apps/chronicle/webapp/scripts/reading-component-smoke.mjs --base-url http://127.0.0.1:5173 --suite r3-harness --output /tmp/chronicle-r3-contract-browser
```

浏览器使用现有 Vite 开发入口。结构通过不等于语义正确；schema 与显示判定表需独立复核一次，不能把未定义产品问题留给后续各组件自行决定。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
