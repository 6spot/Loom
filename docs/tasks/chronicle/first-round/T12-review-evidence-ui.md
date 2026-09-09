---
task: C2-R1-T12
issue: 562
kind: leaf
parent: C2-R1
status: in_progress
depends_on: [C2-R1-T10, C2-R1-T11]
created_at: 2026-09-08
started_at: 2026-09-09
completed_at:
completion_pr:
merge_sha:
---

# 审核证据展开、逐组来源与整章阅读界面

## Scope

[Issue #562](https://github.com/6spot/Loom/issues/562) owns the bounded implementation checklist. 审核比较先看到两侧真实来源和上下文，各组例外能核对，展开全文不打断连续操作。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

 ## Acceptance

 - [x] 无Claim、chapter_pair、published batch全部候选来源可检查。
 - [x] 片段到整章分页明确未完状态，点引用不跳页首，决定和例外草稿不丢。
 - [x] 相同文字不同revision可明确区别；异步迟到不串材料；恶意HTML不执行。
 - [x] 回归T11底部连审、失败保留、跳过和范围恢复仍通过。

 ## Verification

 Implementation complete on branch `agent/executor/f300990d4a77`, delivery PR pending merge. T10 (`4f76f22`) and T11 (`777c8ad`) are merged on the default branch; this task consumes their `contexts`/`sources` API and draft/queue ownership without redefining them. All commands below ran 2026-09-09 against the delivery head:

 - `npm --prefix apps/chronicle/webapp test -- tests/review-evidence.test.ts tests/studio-review-human-display.test.ts tests/studio-entity-conflict.test.ts` — 3 files / 18 tests passed (11 new review-evidence tests).
 - `npm --prefix apps/chronicle/webapp test` (full suite, regression check) — 18 files / 89 tests passed.
 - `npm --prefix apps/chronicle/webapp run build` — OK; `run smoke:dist` — PASS; rebuilt `apps/chronicle/web/dist` committed (evidence panel bundles into the existing `StudioReviewDetailPage.js` chunk, styles into `index.css`; no `static_assets.rs` change needed).
 - `cargo test --lib static_assets` in `apps/chronicle/server` — 7 passed, incl. `vite_dist_asset_allowlist_is_complete`.
 - `node apps/chronicle/webapp/scripts/review-flow-smoke.mjs --base-url http://127.0.0.1:5173 --mode mocked-api --suite all` — PASS (real Chromium + mocked Studio HTTP over an isolated Vite service; all T11 queue checks plus 12 new evidence checks: window snippet, inert HTML, highlight mark, unfinished-chapter notice, continued paging to the end, first-page-is-not-the-group, expand-all, per-group evidence in exception cards, no-claim fallback, auxiliary-translation note, failure-keeps-draft, retry recovery).

 Acceptance coverage: `ReviewEvidencePanel`/`ReviewEvidenceSection` take frozen descriptors plus the T11-isolated record objects (no second form or queue); layers are 原文 / 直接Claim / 对象出现 / 事件背景 / 辅助译文 with 章名/来源 header and revision line; internal IDs stay in audit `<details>`; chapter_pair ends render staged via `stagedSideLabel` (backend `review_mode` passthrough, per-context staged provenance without it); group/member cursors expand explicitly with outstanding counts; request keys bind review/plan/context/artifact with a sequence guard; collapse restores trigger focus and scroll without touching drafts; text renders only from server segments as plain nodes. Review fixes during implementation: hook-order crash (evidence lookup moved above early returns) and 409 auto-retry masking (window query `retry: false`).

  Not verified: real-backend end-to-end (explicitly T18 scope; this task proves UI behavior with mocked HTTP per the Issue). Post-merge reconciliation (`completion_pr`/`merge_sha`, Issue close) is still required per `docs/development/task-completion.md` and must happen after the delivery PR merges.

  Review fix 2026-09-09 (Reviewer CHANGES_REQUIRED on PR #611):

  - Task Ledger front matter had indented YAML fields/closing delimiter from the delivery edit, failing `Chronicle first-round checks` (`missing YAML front matter`). Restored unindented delimiters/fields; verified with a YAML parse of the file head.
  - `ReviewEvidencePanel` anchor switches cleared chapter pages but never invalidated the in-flight flight: added a `createEvidenceRequestGuard()` helper (`studio-api.ts`, pure and unit-tested) and wired it so review/plan/context/anchor transitions invalidate outstanding chapter loads; only the current token writes pages, errors or the busy flag. Identity transitions also reset the busy flag so a stale flight's `finally` can neither clobber the new anchor nor leave it stuck.
  - `ReviewEvidenceSection.expandAll` now issues a guard token for the pagination run and drops the whole result when the group/review key moved mid-flight; the groupKey transition effect invalidates and resets the new group to idle.
  - Re-verified on the fix head:
    - `npm --prefix apps/chronicle/webapp test -- tests/review-evidence.test.ts tests/studio-review-human-display.test.ts tests/studio-entity-conflict.test.ts` — 3 files / 21 tests passed (3 new guard race tests).
    - Full `npm test` — 18 files / 92 passed; `run build` OK; `run smoke:dist` PASS; rebuilt `web/dist` (same chunk names, no `static_assets.rs` change needed).
    - `cargo test --lib static_assets` in `apps/chronicle/server` — 7 passed.
    - Smoke `--suite all` — PASS with 3 new race checks (slow anchor-A chapter page vs. immediate anchor-B switch: B loads, A dropped, draft untouched). Negative control: the same script against the pre-fix panel fails at the race step, proving sensitivity.

  ## Progress Log

 - 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
 - 2026-09-09 — Implementation complete within T12 file ownership (evidence panel + CSS, studio-api/review-display extensions, detail-page wiring, unit tests, smoke evidence scenarios, rebuilt dist). Evidence above; delivery PR pending, post-merge reconciliation still open.
 - 2026-09-09 — Reviewer CHANGES_REQUIRED addressed on the same PR: valid ledger front matter, request-guard invalidation on anchor/context/review/group transitions, busy-flag resets, race coverage (unit + browser incl. negative control), re-verified per above; pushed to PR #611, awaiting re-review; merge + default-branch reconciliation still open.
