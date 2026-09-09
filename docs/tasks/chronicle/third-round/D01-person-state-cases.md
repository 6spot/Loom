---
task: C2-R3-D01
issue: 617
kind: leaf
parent: C2-R3
depends_on: [C2-R1-T02]
---

# 真实人物变化链与阶段反例语料

## 范围与交接

[Issue #617](https://github.com/6spot/Loom/issues/617) 给出实施步骤。把现有完整古文变成逐项可核对的第三轮案例输入，固定正确主体、状态变化、来源归属和阶段预期。

- 输入：第一轮 source-pack.json、已提交四章原件及 hash；#550 中已选的授任、兼任、转投、辞还和父祖官职反例。
- 交付：third-round/cases.json、逐案说明和只读重定位检查；每案标明 real/synthetic、来源 SHA、code-point 范围或 quote/occurrence、人物与阶段、允许与禁止的显示结果。
- 前置：[C2-R1-T02](https://github.com/6spot/Loom/issues/552)

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §§2–3、9 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/corpus/third-round/README.md（新）`
- `apps/chronicle/corpus/third-round/cases.json（新）`
- `apps/chronicle/corpus/third-round/walkthrough.md（新）`
- `apps/chronicle/corpus/test_third_round_cases.py（新）`

可与 D02 并行。只写第三轮案例和自己的校验文件，第一轮原件、上传材料和 source-pack 不改；T01 消费这份案例目录。

## 验收

- [ ] 至少 16 个案例有明确预期与禁止结果，真实/合成标签完整。
- [ ] 全部真实引用能对冻结原件重定位，正文/裴注/引书归属不丢。
- [ ] 不存在把父祖官职、事件角色、未来头衔赋给当前人物的正确样例。
- [ ] 未修改或复制第一轮原件，代码检查不把人工预期伪装成真实模型结果。

## 验证要求

```bash
python3 -m unittest discover -s apps/chronicle/corpus -p 'test_third_round_cases.py' -v
python3 -m unittest discover -s apps/chronicle/corpus -p 'test_first_round_pack.py' -v
```

原文逐案核对属于内容检查，程序定位通过不能替代语义判断。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
