---
task: C2-R3-D02
issue: 618
kind: leaf
parent: C2-R3
depends_on: []
---

# 人物阶段资料与依据审核的桌面、窄屏交互设计

## 范围与交接

[Issue #618](https://github.com/6spot/Loom/issues/618) 记录实施标准。在正式页面与组件中落实紧凑人物／地点状态、两档标记、人物详情和集中审核交互；沿用 C2-R2E 已接入的 HistoryPage，不再新建独立静态设计站。

- 输入：第二轮 reading-experience.md 的布局/字体/导航合同；第三轮本契约；现有周瑜、刘备原文核对点和明确标注的合成交互数据。
- 交付：正式组件的桌面/中屏/窄屏场景、交互状态矩阵和浏览器证据；为 T11/T12 固定默认状态、人物详情层级和回焦行为。
- 前置：无；使用现有已提交合同与语料开始设计。

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §§1–2、5、8 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/webapp/tests/fixtures/reading/scenes/person-state-harness/**`
- `apps/chronicle/webapp/tests/reading-browser/person-state-harness.mjs`
- 本任务的交互矩阵与浏览器证据；公共组件由 T11/T12 按文件交接实施。

可与 D01 并行，不依赖其新案例完成。使用既有 token 与 Vite 场景入口；App、全局 CSS、package/lock 和 dist 统一由 T13 接线。

## 验收

- [ ] 四种宽度均能操作正式组件场景；每人／地点独占紧凑一行，当前状态与人物经历分开，阅读主次和手机入口清楚。
- [ ] 正常、不明确、空、加载失败、兼任、分歧和 process/ambiguous 状态都有确定呈现。
- [ ] 颜色以外能辨识两档；正常/弱化文字都满足 WCAG AA，触屏和键盘能走通来源查看。
- [ ] 审核在页底可保存并下一项；批量与例外范围、引述限定语和错误保留清楚。

## 验证要求

```bash
git diff --check
npm --prefix apps/chronicle/webapp run dev -- --host 127.0.0.1
```

使用同一 Vite 入口，用真实浏览器逐项操作并记录尺寸/缩放/截图。合成场景明确标记，不冒充真实内容验收；不自动生成背景图。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
