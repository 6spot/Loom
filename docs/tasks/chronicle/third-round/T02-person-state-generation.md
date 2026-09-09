---
task: C2-R3-T02
issue: 620
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T01, C2-R2-T03]
---

# 完整章联合生成阶段事实并接入现有 provider

## 范围与交接

[Issue #620](https://github.com/6spot/Loom/issues/620) 给出实施步骤。一次完整自然章的翻译/抽取同时产出 0.3 阶段资料，保留归属、完整上下文和现有失败/恢复审计。

- 输入：T01 schemas/validator；现有整章 request、ChapterLimits、模型 provider、accepted artifact；D01 真实例子作为 prompt 核对材料。
- 交付：生产0.3的唯一版本注册与 provider 接线；valid/invalid/repair fixtures及运输重试回归。
- 前置：[C2-R3-T01](https://github.com/6spot/Loom/issues/619)、[C2-R2-T03](https://github.com/6spot/Loom/issues/572)

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §§3–4 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/persistence/chapter_contract.py（仅版本注册/分派）`
- `apps/chronicle/persistence/chapter_prompt.py`
- `apps/chronicle/persistence/chapter_extraction.py`
- `apps/chronicle/persistence/test_person_state_extraction_unit.py（新）`
- `apps/chronicle/worker/extraction_model_schema.py`
- `apps/chronicle/worker/model_provider.py`
- `apps/chronicle/worker/fixture_model.py`
- `apps/chronicle/worker/test_person_state_provider_unit.py（新）`
- `apps/chronicle/docs/extraction.md`

可与 T03/T05 及独立 UI 并行。只接生成与验收，不改 assembly、迁移、publish worker 或路由；T08 接生产流程。

## 验收

- [ ] 一次整章请求包含翻译、C0记录、reading 和 person_states，接受原子性完整。
- [ ] 初次不合格最多一次整章修正，截断/超限/第二次失败不产生 accepted 结果。
- [ ] 父祖、引述、推荐和临时角色在提示与反例中明确约束；全部事实可追到原文。
- [ ] 恢复/运输重试不多开语义生成链，旧阶段 contract 局部回归保持有效。

## 验证要求

```bash
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_person_state_extraction_unit.py' -v
python3 -m unittest discover -s apps/chronicle/worker -p 'test_person_state_provider_unit.py' -v
python3 -m unittest discover -s apps/chronicle/worker -p 'test_model_provider_transport_retry_unit.py' -v
```

本任务离线验证调用与契约；真实 provider 内容正确性由 T15 逐案核对。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
