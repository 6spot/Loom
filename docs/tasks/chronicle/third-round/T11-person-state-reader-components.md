---
task: C2-R3-T11
issue: 629
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T01, C2-R3-D02, C2-R2-T14]
---

# 阅读人物与地点的紧凑当时状态组件

## 范围与交接

[Issue #629](https://github.com/6spot/Loom/issues/629) 对应本任务；具体实施步骤、文件归属和验收要求保留在下文。实现按当前阶段显示人物资料的独立组件，保持正文优先，并让不明确项仍然好读、可查。

- 输入：D02正式组件场景、T01 typed fixture/runner；C2-R2E HistoryPage 当时状态与旧 ReadingContextPanel 的来源、事件回调。
- 交付：PersonStateItems/PersonStateDetails及ReadingContextPanel阶段slot；props消费T01摘要/详情和onOpenDetails/onSource/onEvent回调；独立显示helper与浏览器scene/spec。
- 前置：[C2-R3-T01](https://github.com/6spot/Loom/issues/619)、[C2-R3-D02](https://github.com/6spot/Loom/issues/618)、[C2-R2-T14](https://github.com/6spot/Loom/issues/583)

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §§1–2、8 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/webapp/src/components/reading/PersonStateItems.tsx（新）`
- `apps/chronicle/webapp/src/components/reading/PersonStateDetails.tsx（新）`
- `apps/chronicle/webapp/src/components/reading/ReadingContextPanel.tsx（仅阶段slot）`
- `apps/chronicle/webapp/src/lib/person-state-display.ts（新）`
- `apps/chronicle/webapp/src/styles/person-state.css（新）`
- `apps/chronicle/webapp/tests/person-state-display.test.ts（新）`
- `apps/chronicle/webapp/tests/fixtures/reading/scenes/person-states/**（新）`
- `apps/chronicle/webapp/tests/reading-browser/person-states.mjs（新）`

可与 T12、后端模块并行。只接props/loader callbacks，不改App、API client、controller、全局CSS或dist；T13统一接线。

默认每人一行：姓名及当时官职／爵号／效力；每个地点同样独占一行，显示行政归属／控制。重要性来自已审核正文的主体关联，其他人物通过搜索进入详情。出使、进入荆州、参与战斗等行为进入人物经历，不重新加入默认侧栏。“当前／附近事件”只消费经过审核的精选 entry_points，不渲染全部抽取 Event。

## 实施步骤

1. 每人独占紧凑一行，显示姓名及当时官职／爵号／效力；每个地点同样逐行显示行政归属／控制。默认只列本段重要主体；人物经历、角色和变化进入详情，不恢复三层行为列表。附近事件仅消费经过审核的 entry_points。
2. 按每条DTO certainty渲染实心/空心与两档墨色；限定语始终可见，原因和来源按需打开，不从confidence/年份推断颜色。
3. 支持兼任、更多项分页、process多阶段、ambiguous、暂无记载、阶段未明和加载/失败；不以全生平简介或最后头衔补空。
4. 复用来源/事件/实体回调及触屏、聚焦、Escape/回焦行为；更新人物列表不抢焦点，操作区域适配窄屏。
5. PersonStateDetails 提供按时间展开的有据经历及身份变化，作为 T13 独立人物页的受控内容组件；人物页布局、路由及主历史返回由 T13 接线。
6. 在自己的 scene/spec 中操作所有状态、200% 缩放、键盘／触屏和 reduced-motion，记录可读性与视觉截图。

## 验收

- [ ] 同人各项可一明一暗，颜色外有标识，不明确项仍可操作且文本满足AA。
- [ ] 兼任、未知、过程和分歧不被压为唯一标签；默认只显示当时状态，行动及身份变化在人物详情按阶段查看。
- [ ] 更多项/原因/原文/事件入口可操作，窄屏不挤压正文或遮末行。
- [ ] 独立真实浏览器suite通过，不修改生产路由或伪称已接真实后端。
- [ ] 兼任、未知、过程和分歧不被压为唯一标签；默认只显示当时状态，行动与变化在人物详情按阶段查看。

## 验证要求

```bash
npm --prefix apps/chronicle/webapp test -- tests/person-state-display.test.ts
node apps/chronicle/webapp/scripts/reading-component-smoke.mjs --base-url http://127.0.0.1:5173 --suite person-states --output /tmp/chronicle-r3-reader-components
```

组件scene由Vite提供；此处mock只证明组件行为，真实快照/发布与阅读联动由T14/T15验证。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
