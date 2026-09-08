---
task: C2-R1-T15
issue: 565
kind: leaf
parent: C2-R1
status: in_progress
depends_on: [C2-R1-T01]
created_at: 2026-09-08
started_at: 2026-09-08
completed_at:
completion_pr:
merge_sha:
---

# 完整白话阅读、篇章目录与按需引用组件

## Scope

[Issue #565](https://github.com/6spot/Loom/issues/565) owns the bounded implementation checklist. 用真实组件呈现单栏完整白话和按需原文，独立于现有审核页与共享路由先完成。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 长章末段可达，默认无逐句双栏，来源按需展开不丢阅读位置。
- [ ] 多引用/长章分页、错误重试、快速切换两publication不会串旧响应。
- [ ] 键盘与移动尺寸可用，来源恶意HTML不执行，无摘要冒充全文。
- [ ] 组件harness有真实交互证据；未挂接模块构建不改变生产dist。

## Verification

Delivery branch evidence (2026-09-08, pre-merge; post-merge reconciliation still required per task-completion):

- `npm --prefix apps/chronicle/webapp test -- tests/chapter-reader.test.ts` — 19/19 pass (fetch/SSR/contract/conformance + `mergeDirectoryPages` + navigation/load-more affordances + later-page-failure keeps rows with retry).
- `npx playwright test --config tests/fixtures/chapter-reader/harness/playwright.config.ts` — 7/7 pass: real mount/click/keyboard/async evidence (directory cursor pagination + directory→chapter navigation, on-demand source open/expand/paginate, Escape-close focus restore, source + chapter retry, directory page-failure keeps rows with inline error + load-more retry, fast-switch isolation across two publications and two anchors, malicious HTML inert).
- `npm --prefix apps/chronicle/webapp test` (full webapp suite) — 61/61 pass, no regressions.
- `npm --prefix apps/chronicle/webapp run lint` (`tsc --noEmit`) — clean.
- `npm --prefix apps/chronicle/webapp run build` — succeeds; `git status` shows no change under `apps/chronicle/web/dist` (module not yet wired to App, T17 owns routing).
- `git diff --check` — clean. No new packages/lockfile changes (harness reuses `@playwright/test` + bundled chromium + vite).

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-08 — Fixed the last Reviewer blocker on the same delivery branch/PR: later directory-page failures now keep loaded rows, show an inline `chapter-index-page-error` with the load-more button as retry (never misreported as finished); added Vitest + Playwright pagination-failure regression tests. Still no App/router/global-CSS/dist changes. Awaiting re-review/merge; completion_pr/merge_sha reconciliation pending post-merge.
