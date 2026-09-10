---
task: C2-R3-T03
issue: 621
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T01, C2-R2-T04]
---

# 跨章阶段依据 remap 与不可变证据组装

## 范围与交接

[Issue #621](https://github.com/6spot/Loom/issues/621) 给出实施步骤。将各章 local 阶段资料送入同一 revision namespace，保留原始归属并提供确定的状态证据输入。

- 输入：全部预期0.3 accepted artifacts；R2/R1 已有 chapter→revision ref map 和 reading manifest；T01 类型。
- 交付：person_state_assembly.py 及 assembled report 的 evidence manifest/来源映射；不分配 canonical ID。
- 前置：[C2-R3-T01](https://github.com/6spot/Loom/issues/619)、[C2-R2-T04](https://github.com/6spot/Loom/issues/573)

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §§3–4 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/persistence/person_state_assembly.py（新）`
- `apps/chronicle/persistence/assembly.py（本轮唯一 owner）`
- `apps/chronicle/persistence/test_person_state_assembly_unit.py（新）`
- `apps/chronicle/docs/assembly.md`

可与 T02/T05 并行。assembly.py 从 R2-T04 顺序接手；T08 只调用，不二次实现映射。

## 验收

- [ ] 全部新引用闭合并保留原章依据，跨章相同 local ID 不冲突。
- [ ] 同名不同实体、事件角色、限定语及分歧仍分开；组装不引入 same-link。
- [ ] 缺章、混版、漂移或错误范围失败，不能发布只带部分人物资料的译文。
- [ ] 相同输入的排序和 hash 可重复；assembly 无网络/DB/模型副作用。

## 验证要求

```bash
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_person_state_assembly_unit.py' -v
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_reading_assembly_unit.py' -v
```

逐项比对 source ref→revision ref→fixture canonical map，避免只验总数或 JSON 可解析。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
