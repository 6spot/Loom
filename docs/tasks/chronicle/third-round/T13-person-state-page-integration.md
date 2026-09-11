---
task: C2-R3-T13
issue: 631
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T08, C2-R3-T10, C2-R3-T11, C2-R3-T12, C2-R2-T15]
---

# 统一接入阅读阶段联动、混合审核页面与生产构建

## 范围与交接

[Issue #631](https://github.com/6spot/Loom/issues/631) 对应本任务；具体实施步骤、文件归属和验收要求保留在下文。把已验收的模块接入真正阅读/Studio页面，保证滚动、返回、刷新、迟到请求与审核草稿都对应同一上下文。

- 输入：生产0.3与API、T11/T12组件、C2-R2E HistoryPage 与唯一 useReadingPosition、review-session 及 NarrativeReviewPanel；D02正式组件场景。
- 交付：单controller驱动的阶段联动、紧凑人物／地点状态、独立人物详情及主历史往返、状态审核分派、匹配web/dist/static注册及集成回归。
- 前置：[C2-R3-T08](https://github.com/6spot/Loom/issues/626)、[C2-R3-T10](https://github.com/6spot/Loom/issues/628)、[C2-R3-T11](https://github.com/6spot/Loom/issues/629)、[C2-R3-T12](https://github.com/6spot/Loom/issues/630)、[C2-R2-T15](https://github.com/6spot/Loom/issues/584)

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §§5.1、7–8 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/webapp/src/hooks/usePersonStateContext.ts（新）`
- `apps/chronicle/webapp/src/pages/public/HistoryPage.tsx`
- `apps/chronicle/webapp/src/pages/public/ReadingPage.tsx（来源阅读接线）`
- `apps/chronicle/webapp/src/pages/public/EntityPage.tsx（人物介绍、经历与身份演变时间轴）`
- `apps/chronicle/webapp/src/components/HistoryReturnLink.tsx`
- `apps/chronicle/webapp/src/pages/studio/StudioReviewPage.tsx`
- `apps/chronicle/webapp/src/pages/studio/StudioReviewDetailPage.tsx`
- `apps/chronicle/webapp/src/lib/review-session.ts（scope与判别draft）`
- `apps/chronicle/webapp/src/lib/queries.ts（阶段query key）`
- `apps/chronicle/webapp/src/App.tsx（仅必要接线）`
- `apps/chronicle/webapp/src/lib/routes.ts（仅必要接线）`
- `apps/chronicle/webapp/tests/person-state-context.test.ts（新）`
- `apps/chronicle/webapp/tests/person-state-page-integration.test.ts（新）`
- `apps/chronicle/webapp/tests/review-session.test.ts`
- `apps/chronicle/server/src/app.rs（仅必要SPA接线，T10后）`
- `apps/chronicle/server/src/static_assets.rs`
- `apps/chronicle/server/tests/static_asset_integration.rs`
- `apps/chronicle/web/dist/**`
- `apps/chronicle/docs/ui.md`

唯一生产页面/build/dist owner，所有依赖接口就绪后串行接线。不重写T04规则、R2滚动控制器或T06审核状态机。

## 生产页面保留现有综合链路

Studio 接入第三轮表单时保留已经交付的综合 facts／prose 审核组件和编辑行为；按 #619/#628 的合同请求完整混合队列，草稿按 review_id、scope 和 frozen version 隔离。长页“保存并下一项”必须能跨身份、阶段依据、综合事实、综合正文四种表单工作，不丢编辑或误用提交 DTO。

HistoryPage 与独立人物页使用最终综合发布状态。验收至少走“主历史某段 → 人物详情对应阶段 → 返回原段及段内偏移”，并检查刷新／前进后退、兼任、明确结束及同年不同阶段。正式界面保持重要事件锚点的精选入口；内部任免与阶段变化不得扩成一长串导航。

页面接好但只有来源 ReadingPage 有正确人物状态，或合成场景有状态而正式 history API 没有，均不能算本任务完成。

## 实施步骤

1. 复用 HistoryPage 的唯一 controller；按综合 version/paragraph/phase 一次请求状态摘要，完整 key/abort/迟到检查和有界缓存。来源 unit 只在 ReadingPage 读取。详情与原文按需加载，不另建滚动或 history 控制器。
2. 段落切换立即显示新段重要人物／地点和状态加载态，不能闪现上一段状态；空段清空，旧事hover不改变当前上下文。
3. 接 T11 进入 ReadingContextPanel，传相同综合位置；保持过程／未知、来源面板及返回焦点。EntityPage 左侧概况与时间定位，中间有据个人经历，右侧当前阶段状态／相关人物地点。从正文进入保留阶段，HistoryReturnLink 返回原段及偏移；直接进入人物页不捏造当前年份。
4. Studio 默认请求 all，按 scope 呈现 T12 阶段表单、原 identity 表单或已有 narrative facts/prose 表单；URL/list cursor/open 扫描/draft key 包括 review_scope，三类 scope 的草稿和决定不能串用。
5. 复用保存并下一项及未知提交结果核对，验证两tab、页尾仅跳过、scope切换、back/forward/刷新及跨来源返回。
6. 串行运行web test/build/smoke，提交匹配dist和Rust资源注册；用本地实际页面操作关键路径并记录，完整自动真实栈验收由T14接续。

## 验收

- [ ] 滚动/主动跳转/后退前进/刷新始终显示同一locator的资料，预览旧事不切阶段，迟到结果不覆盖新段。
- [ ] 无逐人N+1或前端累计/撤销历史状态，正文在数据故障时保持可读。
- [ ] 人物详情能读有据介绍、查看按时间发展的经历及身份变化；从历史进入保留阶段，返回恢复原段和段内偏移，直接进入不捏造当前年份。
- [ ] 主阅读默认人物、地点各占紧凑单行并显示状态；事件／时期仅为少量定位入口，不作为正文过滤条件。
- [ ] 混合审核过滤/草稿/连续操作互不串型，保存决定来自服务端且页底可继续。
- [ ] 生产页面与dist/static资源一致，全部相关前端/Rust检查通过；没有第二套controller。
- [ ] 正式综合历史可进入人物页对应阶段并返回原段及段内偏移；四类审核表单保持可用，不能只用来源页或 fixture 验收。
- [ ] 独立人物页可阅读介绍和时间化经历／身份变化，来源按需查看；从正文往返及直接访问均有明确语义。
- [ ] 人物与地点分别紧凑逐行显示当时状态；时期／事件是少量定位入口，不过滤前后正文。

## 验证要求

```bash
npm --prefix apps/chronicle/webapp test
npm --prefix apps/chronicle/webapp run build
npm --prefix apps/chronicle/webapp run smoke:dist
cargo test --manifest-path apps/chronicle/server/Cargo.toml --test static_asset_integration
cargo fmt --manifest-path apps/chronicle/server/Cargo.toml -- --check
```

安装、build、dist和Git写入预约串行窗口；独立组件通过不替代生产页实际打开和操作记录。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
