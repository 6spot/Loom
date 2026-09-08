# Chapter reader 组件浏览器 harness（C2-R1-T15）

本目录是 T15 阅读组件的可运行交互 harness：真实挂载组件、真实点击/键盘、
真实异步状态（延迟、一次性失败、快速切换），固定 DTO 来自 T01 冻结合同。
新模块尚未挂接 App/路由与生产 dist（T17 统一接线），harness 用本地 state
完成“目录 → 章节”导航，不导入 App/router。

## 运行

```bash
npm --prefix apps/chronicle/webapp test -- tests/chapter-reader.test.ts
npx playwright test --config tests/fixtures/chapter-reader/harness/playwright.config.ts
```

Playwright 配置会自行起停 `vite dev`（127.0.0.1:5193，仅承载本目录的
`index.html`）；生产构建只打包根 `index.html`，harness 不进 dist。
所用依赖（`@playwright/test`、chromium、vite、react-query）均为仓库已有，
无新增 package/lock。

## 覆盖（`harness.spec.ts`，6 用例）

1. 目录 cursor 分页＋进入章节：第一页 1 条 →“读下一页”→ 2 条＋“目录已读完”；
   点击条目进入单栏完整白话（含无引用段），默认无双栏。
2. 按需原文：点击引用 →window 片段；“展开整章”→ 章视图；“继续读下一页”
   用 cursor 取第二页；Escape 关闭后面板消失、焦点回到触发按钮。
3. 原文失败重试：一次性失败 → 错误卡＋正文保留 → 重试恢复。
4. 章节失败重试：错误卡 → 重试 → 整章呈现。
5. 快速切换：在途慢响应下连切两章，旧响应不覆盖新视图；同章连切两引用，
   面板只呈现第二个 anchor。
6. 恶意 HTML：`?panel=security` 直渲染含 `<img onerror>`/`<script>` 的
   segments；断言无 script/img 元素生成、`__pwned` 未定义、文本转义呈现。

## DTO fixtures（全部源自 T01 冻结合同）

- `chapter-detail.json` — 由 `public-chapter-response-example.json` 派生；
  `source_anchor_ids` 是服务端下发的 block→anchor 映射在 T14 reader API 中的占位，
  harness 显式携带，浏览器绝不猜测。`ent_003`（“公”）故意无 canonical 目标，
  验证歧义引用如实显示为文本、不伪造 `/entities/ent_003` 链接。
- `chapter-detail-b.json` — harness 自备第二 publication，用于切换隔离检查。
- `source-window.json` — 同合同的 `public-source-response-example.json` 原样。
- `source-chapter-page1.json` / `source-chapter-page2.json` — 整章视图两页，
  `next_cursor=chapter-cursor-p2` 串联，验证续页与 `has_more`。
- `directory.json` / `directory-page1.json` / `directory-page2.json` —
  全量目录与两页游标目录，验证分页合并与切换。
- `source-malicious.json` — 合成负例：segments 含 `<img onerror>` 与 `<script>`，
  验证来源恶意 HTML 只作普通文本渲染、不执行。

## 手动复核清单（自动化之外，挂接前抽查）

1. 键盘 Tab 可达所有按钮；窄屏单栏无横向滚动。
2. 关闭原文后面板阅读位置不跳顶（自动化已验焦点恢复）。

## 与生产 dist 的关系

本 harness 与 `src/pages/public/Chapter*.tsx`、`src/components/ChapterSourceReference.tsx`、
`src/lib/chapter-reader.ts`、`src/styles/chapter-reader.css` 均未被 `App.tsx` /
`lib/routes.ts` 引用（见 `chapter-reader.test.ts`“未挂接生产入口”用例），
`npm run build` 不改变 `apps/chronicle/web/dist`。
