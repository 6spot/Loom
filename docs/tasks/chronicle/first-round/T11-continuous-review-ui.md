---
task: C2-R1-T11
issue: 561
kind: leaf
parent: C2-R1
status: in_progress
depends_on: [C2-R1-T09]
created_at: 2026-09-08
started_at: 2026-09-09
completed_at:
completion_pr:
merge_sha:
---

# 保存并下一项、暂时跳过、草稿和队列位置恢复

## Scope

[Issue #561](https://github.com/6spot/Loom/issues/561) owns the bounded implementation checklist. 在长审核页底部直接完成并进入下一项；失败不丢草稿，返回不丢范围和阅读位置。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [x] 在长页最底部能保存并下一项，无需滚回顶部；返回队列保持scope/位置。
- [x] 450项翻页、两tab竞争、晚提交新项、最后一项/只剩跳过项行为符合合同。
- [x] Entity→Event、A组→B组不串草稿；失败刷新草稿保留，明确成功才前進。
- [x] 暂时跳过仍open并阻塞resume；明确uncertain才提交；已处理记录不覆盖。

## Verification

Implementation complete on branch `agent/executor/7ba68854ea09`, delivery PR pending merge. All commands below ran 2026-09-09 against the delivery head:

- `npm --prefix apps/chronicle/webapp test -- tests/review-session.test.ts tests/studio-reviews.test.ts tests/studio-entity-conflict.test.ts` — 3 files / 20 tests passed (12 new review-session tests).
- `npm --prefix apps/chronicle/webapp test` (full suite, regression check) — 16 files / 55 tests passed.
- `npm --prefix apps/chronicle/webapp run build` — OK; `run smoke:dist` — PASS; rebuilt `apps/chronicle/web/dist` committed (new shared `review-session.js` chunk registered in `server/src/static_assets.rs`, retired `review-display.js` chunk removed from the allowlist).
- `cargo test -p chronicle-server --lib` — 23 passed, incl. `vite_dist_asset_allowlist_is_complete`.
- `node apps/chronicle/webapp/scripts/review-flow-smoke.mjs --base-url http://127.0.0.1:5173 --mode mocked-api --suite queue` — PASS (23 checks, real Chromium + mocked Studio HTTP over an isolated Vite service: scope URL, keyset pagination, sticky bottom bar, draft reload retention, save-and-next advance with single POST, skip without POST, back-to-queue scope, 409 retention + reload, entity/event isolation, only-skipped end state with still-open count).
- Same script with `--suite all` — PASS (adds the import-detail job-scope entry).
- `python3 tools/validator_ready.py --root docs/tasks/chronicle/first-round --check` — valid.

Review fix 2026-09-09 (Reviewer CHANGES_REQUIRED on PR #597, deep-page advance): `findNextThroughServer` used id-index lookup from a fresh open list, so after a successful POST removed the current review, a deep-page item (absent from the list) restarted traversal at the head. Fixed by capturing the `(created_at, review_id)` sort anchor before the POST/skip and continuing strictly after it via new `findNextAfterAnchor`/`compareReviewSortKey` helpers (Postgres ASC NULLS LAST mirrored). Re-verified on the fix head:

- `npm --prefix apps/chronicle/webapp test -- tests/review-session.test.ts tests/studio-reviews.test.ts tests/studio-entity-conflict.test.ts` — 3 files / 24 tests passed (4 new anchor regression tests incl. 450-item deep-page removal).
- Full `npm test` — 16 files / 59 passed; `run build` OK; `run smoke:dist` PASS; rebuilt `web/dist` (same chunk names, no `static_assets.rs` change needed).
- `cargo test --lib` in `apps/chronicle/server` — 23 passed.
- Smoke `--suite queue` — PASS (24 checks, incl. new deep-page step: saving past page one lands on the anchor successor, not the head); `--suite all` — PASS.
- Validator: reports only the pre-existing cross-task condition `dependency C2-R1-T09 is in_progress, not completed` (T09 code is merged on the default branch; its ledger reconciliation is owned outside T11 scope and was left untouched). No other violations.

Acceptance coverage: queue page reads page-by-page via `listReviewPage` with server `open_count`/`observed_at` (no full-list wrapper consumer remains in pages); detail page fixes the reviewId-change draft reset, isolates drafts by `(review_id, plan_fingerprint)`, advances only after success, re-checks next-item server status (two-tab contention), handles late responses by original id, re-scans from head at the tail (late rows before old cursor), and reports only-skipped/empty end states without claiming import completion. Skip never POSTs. The `listReviews` export is kept deprecated (its traversal contract lives in `tests/studio-reviews.test.ts`, outside T11 file ownership) — UI removal only.

Not verified: real-backend end-to-end (explicitly T18 scope; this task proves UI behavior with mocked HTTP per the Issue); 450-row live pagination (unit + paged-mock traversal cover the algorithm; the mocked queue pages 65 items across cursors). Post-merge reconciliation (`completion_pr`/`merge_sha`, README index, Issue close) is still required per `docs/development/task-completion.md` and must happen after the delivery PR merges.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-09 — Implementation complete within T11 file ownership (session lib + tests, both review pages, job-scope entry, styles, smoke script, rebuilt dist, minimal static-asset registration). Evidence above; delivery PR pending, post-merge reconciliation still open.
- 2026-09-09 — Reviewer CHANGES_REQUIRED addressed on the same PR: anchor-based deep-page advance + regression tests (unit + browser), re-verified per above; pushed to PR #597, awaiting re-review; merge + default-branch reconciliation still open.
