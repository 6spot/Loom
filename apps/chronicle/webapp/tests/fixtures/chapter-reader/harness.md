# Chapter reader 组件浏览器 harness（C2-R1-T15）

本目录是 T15 阅读组件的独立浏览器 harness：固定 DTO + 手动交互清单。
新模块尚未挂接 App/路由与生产 dist（T17 统一接线），因此 harness 先以
静态 DTO 与待挂接的组件清单形式提供真实交互证据的入口；自动化交互证据
见 `tests/chapter-reader.test.ts`（fetch 桩＋迟到响应＋分页＋重试＋SSR 渲染）。

## DTO fixtures（全部源自 T01 冻结合同）

- `chapter-detail.json` — 由 `apps/chronicle/ingestion/fixtures/c2r1-contract/public-chapter-response-example.json`
  派生；`source_anchor_ids` 是服务端下发的 block→anchor 映射在 T14 reader API 中的占位，
  harness 显式携带，浏览器绝不猜测。`ent_003`（“公”）故意无 canonical 目标，
  验证歧义引用如实显示为文本、不伪造 `/entities/ent_003` 链接。
- `source-window.json` — 同合同的 `public-source-response-example.json` 原样。
- `source-chapter-page1.json` / `source-chapter-page2.json` — 整章视图两页，
  `next_cursor=chapter-cursor-p2` 串联，验证续页与 `has_more`。
- `directory.json` — 两个 publication 的目录页，验证快速切换不串旧响应。
- `source-malicious.json` — 合成负例：segments 含 `<img onerror>` 与 `<script>`，
  验证来源恶意 HTML 只作普通文本渲染、不执行。

## 手动交互清单（T17 挂接后在浏览器执行）

1. 打开目录：两个条目可见，publication_id 逐字显示，不混入未发布版本。
2. 打开第一章：全文两段一次呈现；第二段（无引用段）同样展示；默认无双栏。
3. 第一段点两个“看原文”按钮：各发一次 `view=window` 请求；关闭后焦点回到按钮，
   阅读位置不跳顶。
4. 原文面板内“展开整章”：发 `view=chapter` 请求；“继续读下一页”用
   `cursor=chapter-cursor-p2` 取第二页；两页拼接完整。
5. 断网后点“重试”：正文保留，可恢复；快速在两章之间切换：旧响应不覆盖新章。
6. “公”只显示文本、无链接；恶意 segments 用文本展示，DevTools 确认无 script 执行。
7. 键盘 Tab 可达所有按钮，Escape 关闭原文面板；窄屏单栏无横向滚动。

## 与生产 dist 的关系

本 harness 与 `src/pages/public/Chapter*.tsx`、`src/components/ChapterSourceReference.tsx`、
`src/lib/chapter-reader.ts`、`src/styles/chapter-reader.css` 均未被 `App.tsx` /
`lib/routes.ts` 引用（见测试“未挂接生产入口”用例），`npm run build` 不改变
`apps/chronicle/web/dist`。
