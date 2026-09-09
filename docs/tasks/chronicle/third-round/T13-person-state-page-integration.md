---
task: C2-R3-T13
issue: 631
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T08, C2-R3-T10, C2-R3-T11, C2-R3-T12, C2-R2-T15]
---

# 统一接入阅读阶段联动、混合审核页面与生产构建

## 范围与交接

[Issue #631](https://github.com/6spot/Loom/issues/631) 给出实施步骤。把已验收的模块接入真正阅读/Studio页面，保证滚动、返回、刷新、迟到请求与审核草稿都对应同一上下文。

- 输入：生产0.3与API、T11/T12组件、R2唯一ReadingPosition/ReadingPage、R1 review-session；D02设计。
- 交付：单controller驱动的阶段查询hook、生产人物区与状态审核分派、匹配web/dist/static注册及集成回归。
- 前置：[C2-R3-T08](https://github.com/6spot/Loom/issues/626)、[C2-R3-T10](https://github.com/6spot/Loom/issues/628)、[C2-R3-T11](https://github.com/6spot/Loom/issues/629)、[C2-R3-T12](https://github.com/6spot/Loom/issues/630)、[C2-R2-T15](https://github.com/6spot/Loom/issues/584)

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §§5.1、7–8 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/webapp/src/hooks/usePersonStateContext.ts（新）`
- `apps/chronicle/webapp/src/pages/public/ReadingPage.tsx`
- `apps/chronicle/webapp/src/pages/public/EntityPage.tsx（仅阅读上下文入口）`
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

## 验收

- [ ] 滚动/主动跳转/后退前进/刷新始终显示同一locator的资料，预览旧事不切阶段，迟到结果不覆盖新段。
- [ ] 无逐人N+1或前端累计/撤销历史状态，正文在数据故障时保持可读。
- [ ] 混合审核过滤/草稿/连续操作互不串型，保存决定来自服务端且页底可继续。
- [ ] 生产页面与dist/static资源一致，全部相关前端/Rust检查通过；没有第二套controller。

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
