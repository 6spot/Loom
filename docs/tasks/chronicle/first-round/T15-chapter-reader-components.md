---
task: C2-R1-T15
issue: 565
kind: leaf
parent: C2-R1
status: completed
depends_on: [C2-R1-T01]
created_at: 2026-09-08
started_at: 2026-09-08
completed_at: 2026-09-08
completion_pr: 593
merge_sha: 3337a2cd276ffb005a0d4b298c87f44dff48bb10
---

# 完整白话阅读、篇章目录与按需引用组件

## Scope

[Issue #565](https://github.com/6spot/Loom/issues/565) owns the bounded implementation checklist. 用真实组件呈现单栏完整白话和按需原文，独立于现有审核页与共享路由先完成。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [x] 长章末段可达，默认无逐句双栏，来源按需展开不丢阅读位置。
- [x] 多引用/长章分页、错误重试、快速切换两publication不会串旧响应。
- [x] 键盘与移动尺寸可用，来源恶意HTML不执行，无摘要冒充全文。
- [x] 组件harness有真实交互证据；未挂接模块构建不改变生产dist。

## Verification

Delivery branch evidence (2026-09-08, pre-merge; post-merge reconciliation still required per task-completion):

- `npm --prefix apps/chronicle/webapp test -- tests/chapter-reader.test.ts` — 19/19 pass (fetch/SSR/contract/conformance + `mergeDirectoryPages` + navigation/load-more affordances + later-page-failure keeps rows with retry).
- `npx playwright test --config tests/fixtures/chapter-reader/harness/playwright.config.ts` — 7/7 pass: real mount/click/keyboard/async evidence (directory cursor pagination + directory→chapter navigation, on-demand source open/expand/paginate, Escape-close focus restore, source + chapter retry, directory page-failure keeps rows with inline error + load-more retry, fast-switch isolation across two publications and two anchors, malicious HTML inert).
- `npm --prefix apps/chronicle/webapp test` (full webapp suite) — 61/61 pass, no regressions.
- `npm --prefix apps/chronicle/webapp run lint` (`tsc --noEmit`) — clean.
- `npm --prefix apps/chronicle/webapp run build` — succeeds; `git status` shows no change under `apps/chronicle/web/dist` (module not yet wired to App, T17 owns routing).
- `git diff --check` — clean. No new packages/lockfile changes (harness reuses `@playwright/test` + bundled chromium + vite).

2026-09-09 — Post-merge reconciliation (delivery PR #593 MERGED as `3337a2cd276ffb005a0d4b298c87f44dff48bb10` on 2026-09-08; dependency T01 already `completed` on the default branch): front matter now carries actual completion_pr/merge_sha and all acceptance boxes are checked against the delivery evidence above. Post-merge confirmation on the T17 integration head: `npm --prefix apps/chronicle/webapp test` — 18 files / 98 passed (incl. all chapter-reader tests plus the new `revision_ref` join test); the T17 production smoke (real PG + real sidecar + Rust front + Chromium) renders these components against the genuine API — directory, full text, on-demand source window/chapter expansion, Escape/close focus behavior — so the components are proven mounted, not standalone-only. Acceptance box 4 ("unwired build leaves dist alone") held at merge time; the T17 integration then wires App/router/CSS and rebuilds `web/dist` by design (T17 ownership). T17's `chapter-reader.ts` join change is purely additive (`revision_ref` preferred, source `ref` fallback; all pre-existing fixture tests still pass).

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-08 — Fixed the last Reviewer blocker on the same delivery branch/PR: later directory-page failures now keep loaded rows, show an inline `chapter-index-page-error` with the load-more button as retry (never misreported as finished); added Vitest + Playwright pagination-failure regression tests. Still no App/router/global-CSS/dist changes. Awaiting re-review/merge; completion_pr/merge_sha reconciliation pending post-merge.
- 2026-09-09 — Reconciled post-merge (see Verification): PR #593 merged, acceptance checked, T17 integration proves the components in production.
