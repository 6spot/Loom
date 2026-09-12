# C2-R3-D02 人物阶段资料交互 harness（仅测试使用）

本目录属于第三轮 C2-R3-D02，固定「紧凑人物／地点状态、两档明确性、人物详情、
集中审核、独立人物页」的交互与默认状态，供 T11／T12 按文件交接实现正式组件。
**全部场景为合成示例，不是真实史料译文、不是真实模型输出，也不冒充已发布内容。**

不新建独立静态设计站：场景复用正式 `HistoryPage` 的 `.rpage` 左轴／中正文／右栏
骨架、`public-reading.css` / `reading-layout.css` / `reading-context.css` token，以及
正式 `PublicDialog`（关闭时回焦触发元素）。

## 文件

- `index.html` / `main.tsx`：自包含 Vite 入口，`?case=reading|review|entity`。
- `ReadingHarness.tsx`：阅读页（桌面右栏、中屏展开区、窄屏「人物地点」入口）、
  人物详情、依据／原文窗口、回焦与不改阶段。
- `ReviewHarness.tsx`：一章一份阶段依据包审核（按人物变化、共用依据、批量确认、
  逐条例外、页底固定「保存并下一项」、错误保留草稿）。
- `EntityHarness.tsx`：独立人物页三栏（概况与时间定位／经历时间轴／当前阶段状态
  及相关人物地点）；从正文进入保留阶段，返回恢复原段与偏移；直接进入不捏造年份。
- `data.ts`：合成 DTO 数据与既有原文核对点（仅作交互展示）。
- `matrix.ts`：交互状态矩阵，浏览器 spec 逐条断言。
- `person-state-harness.css`：D02 交互样式，颜色外均有文字／形状标识。

## 运行

本目录不自带服务，使用既有 Vite 入口：

```bash
npm --prefix apps/chronicle/webapp run dev -- --host 127.0.0.1
node apps/chronicle/webapp/tests/reading-browser/person-state-harness.mjs \
  --base-url http://127.0.0.1:5173 --scene all --output /tmp/chronicle-r3-d02
```

`person-state-harness.mjs` 同时导出 `run(ctx)`（`check` / `info` / `screenshot` /
`openScene`），T01 在共享 runner 注册 r3 suite 时可复用；场景名与
`?case=` 选择方式保持稳定。

## 交互状态矩阵

| 状态 | 确定呈现 |
| --- | --- |
| 明确 | 实心 ●＋「明确」可访问名称、正常墨色、可点依据 |
| 不明确 | 空心 ○＋「存疑」、灰墨色、**非 disabled**、原因可查 |
| 暂无记载 | 显示「暂无记载」，不生成虚构候选身份 |
| 阶段未明确 | 显示「阶段未明确」材料，不当作此前任职或当前身份 |
| 加载中 | 显式加载状态，不用上一段身份冒充当前段 |
| 加载失败 | 显式错误＋重试，已读正文保留，不伪造状态 |
| 兼任 | 多项并列，不压成最高官职 |
| 多阶段过程 | 保留全过程并标明阶段顺序 |
| 多解释 | 分别呈现材料，不压成唯一标签 |
| 来源分歧 | 保留双方归属与各自主张，不取胜者 |
| 同人部分明确 | 同人不同项一明一暗，不整体标暗 |
| 空段 | 明确「本段还没有关联人物或地点」，不清空正文 |

## 浏览器证据

`--scene all` 实测（真实 Chromium）覆盖 1440×900、1024×768、390×844、320×568、
200% 字号、键盘与触屏。生成截图：

- `d02-reading-1440.png` / `d02-reading-1440-detail.png` / `d02-reading-1440-evidence.png`
- `d02-reading-1024.png` / `d02-reading-phone-390.png` / `d02-reading-phone-320.png`
- `d02-reading-200pct.png`
- `d02-review-1440.png` / `d02-review-390.png`
- `d02-entity-1440.png` / `d02-entity-390.png`
- `result.json`：逐项 check 与对比度／触控面积数据

实测对比度（WCAG，背景 `#faf8f3`）：明确标题 13.15:1、存疑标题 4.91:1，
均 ≥ AA 4.5:1；可交互元素最小高度 44px（200% 字号下 88px）。

## 未验证项

- 未接入生产 App／路由／HTTP client，也未写 `web/dist`（由 T13 统一接线）。
- 真实整章 0.3 产物、真实 provider 内容与发布链路由 T15 验收；本 harness 只固定
  交互与默认状态。
- `run(ctx)` 与共享 `reading-component-smoke.mjs` 的 suite 注册由 T01 完成，本任务
  不改共享 runner。
