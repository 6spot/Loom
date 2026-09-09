---
task: C2-R3-D02
issue: 618
kind: leaf
parent: C2-R3
depends_on: []
---

# 人物阶段资料与依据审核的桌面、窄屏交互设计

## 范围与交接

[Issue #618](https://github.com/6spot/Loom/issues/618) 给出实施步骤。在写生产页面前给出可直接打开的设计，落实书卷阅读中的人物层级、两档标记、过程与分歧，以及集中审核交互。

- 输入：第二轮 reading-experience.md 的布局/字体/导航合同；第三轮本契约；现有周瑜、刘备原文核对点和明确标注的合成交互数据。
- 交付：同一静态设计页的桌面/中屏/窄屏场景、交互状态矩阵和截图说明；为 T11/T12 固定默认内容、展开层级和回焦行为。
- 前置：无；使用现有已提交合同与语料开始设计。

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §§1–2、5、8 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/docs/design/person-states/index.html（新）`
- `apps/chronicle/docs/design/person-states/design.css（新）`
- `apps/chronicle/docs/design/person-states/README.md（新）`
- `apps/chronicle/docs/design/person-states/screenshots/**（新）`

可与 D01 并行，不依赖其新案例完成。设计只读既有 token，不改 App、全局 CSS、package/lock 或 dist；T11/T12 消费设计。

## 验收

- [ ] 四种宽度均有可打开设计，阅读主次和手机入口清楚。
- [ ] 正常、不明确、空、加载失败、兼任、分歧和 process/ambiguous 状态都有确定呈现。
- [ ] 颜色以外能辨识两档；正常/弱化文字都满足 WCAG AA，触屏和键盘能走通来源查看。
- [ ] 审核在页底可保存并下一项；批量与例外范围、引述限定语和错误保留清楚。

## 验证要求

```bash
git diff --check
python3 -m http.server 5174 --bind 127.0.0.1 --directory apps/chronicle/docs/design/person-states
```

http.server 是预览入口，检查后停止；用真实浏览器逐项操作并记录尺寸/缩放/截图。此任务不增加生产页面或自动生成背景图。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
