---
task: C2-R3-D01
issue: 617
kind: leaf
parent: C2-R3
depends_on: [C2-R1-T02]
---

# 真实人物变化链与阶段反例语料

## 范围与交接

[Issue #617](https://github.com/6spot/Loom/issues/617) 对应本任务；具体实施步骤、文件归属和验收要求保留在下文。把现有完整古文变成逐项可核对的第三轮案例输入，固定正确主体、状态变化、来源归属和阶段预期。

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

## 实施步骤

1. 核对 source-pack 与四章原件的版本和 hash，引用已有整章材料，不另下载同书、复制全文或截取一段冒充完整章。
2. 至少整理 16 案；真实案包括周瑜授任/兼任、刘备转投/辞还、父祖官职和注释归属；逐案说明原文能够证明什么、不能证明什么。
3. 缺少真实证据的边界用 synthetic 标注：同年顺序未知、跨章回溯、明确结束后再次任职、未来头衔、空态、对立来源；不得为凑数量发明史料。
4. 预期按人物/维度/阶段/结论/明确性/原因/来源记录；先区分推荐、自称、追赠、引述及事件角色，再决定是否进入当前身份。
5. 添加重定位检查，验证 UTF-8 规范化、来源 hash、精确 quote/occurrence、唯一 case_id；案例说明与原文不一致时失败。

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
