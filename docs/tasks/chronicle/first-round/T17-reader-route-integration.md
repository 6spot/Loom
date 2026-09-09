---
task: C2-R1-T17
issue: 567
kind: leaf
parent: C2-R1
status: in_progress
depends_on: [C2-R1-T12, C2-R1-T14, C2-R1-T15, C2-R1-T16]
created_at: 2026-09-08
started_at: 2026-09-09
completed_at:
completion_pr: 612
merge_sha:
---

# 篇章阅读接入公开导航、Rust路由与构建资源

## Scope

[Issue #567](https://github.com/6spot/Loom/issues/567) owns the bounded implementation checklist. 用户从现有公开导航就能进入完整白话篇章，直接打开和刷新也可用，浏览器实际走生产Rust front。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [x] 从公开导航完成目录→完整章→引用→整章原文→返回正文，首尾无缺失。
- [x] 直接打开/刷新chapters路径成功，全部静态资源由Rust正确返回。
- [x] 未发布章节public404，Studio仍需认证；API错误保留JSON状态码。
- [x] 生产build与提交dist一致，现有审核连审及事件/人物页面回归通过。

## Verification

All commands below ran 2026-09-09 on delivery PR #612 head (branch `agent/executor/2b681b95149d`):

- `npm --prefix apps/chronicle/webapp test` — 18 files / 98 passed (routes, route-split, chapter-reader incl. new `revision_ref` join test, all review/human-display/conflict suites).
- `npm --prefix apps/chronicle/webapp run build` — OK; `run smoke:dist` — PASS; rebuilt `apps/chronicle/web/dist` committed (chapters bundle into existing `index.js`; deterministic names unchanged, no `static_assets.rs` allowlist addition needed).
- `cargo test --manifest-path apps/chronicle/server/Cargo.toml` — all suites pass (incl. new `reader_chapters_integration` 5 tests); `cargo clippy --all-targets -- -D warnings` — clean; `cargo fmt --check` — clean; `git diff --check` — clean.
- `test_reader_chapters_postgres.py` — 15 tests OK; `test_reader_chapters_unit.py` — 8 tests OK (T14 seam re-verified).
- Isolated-service smoke through the production Rust front with a genuine published ID (NOT a mock upstream): PG18 control service + isolated DB `chronicle_t14_68a...` (T14 fixture publish path) + real Python sidecar + real `chronicle-server` + real Chromium: `node apps/chronicle/webapp/scripts/chapter-reader-smoke.mjs --base-url http://127.0.0.1:18081 --publication-id 01a084ab-0505-753d-abd3-8ead0794fe7e` — PASS, 19 checks (public nav 篇章 → directory → full 2-block chapter → canonical ref links → source anchors → source window → whole-chapter view → close back to text → footer → direct open → refresh → mobile), 6 screenshots. Unknown publications stay JSON 404; Studio still 401-gated.
- Reader seam fix (required by the acceptance journey, flagged as cross-ownership integration): `handle_detail` now serves per-block `source_anchor_ids` and per-ref `revision_ref` (source `ref` preserved); `chapter-reader.ts` joins through `revision_ref` with source-`ref` fallback. Without it the real API exposed zero source buttons and zero ref links (proven by the hardened smoke FAIL before the fix). The smoke script now FAILS when a chapter exposes no source anchors instead of skipping.
- Dependency reconciliation: T12 (#611/`3e4c6e9`), T14 (#610/`66ef5b4`), T15 (#593/`3337a2c`), T16 (#606/`d5cd8b8`) delivery PRs are all MERGED on the default branch; their ledgers carry actual completion_pr/merge_sha in this same PR. `merge_sha` for T17 itself stays empty until PR #612 merges (post-merge follow-up per task-completion, no separate bookkeeping PR).

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-09 — Implemented and verified (see Verification). Reviewer CHANGES_REQUIRED round 2 addressed in the same PR #612: dependency ledgers reconciled with merge actuals, isolated-service smoke with genuine published ID, hardened smoke gate, T14/T15 reader-seam fix with regression tests. Awaiting re-review; merge + T17 merge_sha follow-up still open.
