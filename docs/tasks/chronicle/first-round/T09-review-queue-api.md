---
task: C2-R1-T09
issue: 559
kind: leaf
parent: C2-R1
status: in_progress
depends_on: []
created_at: 2026-09-08
started_at: 2026-09-08
completed_at:
completion_pr:
merge_sha:
---

# 审核队列范围、稳定分页及全部页消费者

## Scope

[Issue #559](https://github.com/6spot/Loom/issues/559) owns the bounded implementation checklist. 消除首200项限制和offset分页漏审，为连续审核提供真实范围、稳定游标和待审计数。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [x] 450项以上、相同created_at、多job和kind的筛选/翻页/计数正确。
- [x] 处理前页后继续游标不会漏中间项；旧cursor不能套到别的scope。
- [x] 晚提交落在旧cursor前的项能在从头重读时发现；API不谎称冻结总数。
- [ ] 现页面和验收脚本仍可工作，没有首200项作为全量结论的残留消费者。

## Verification

Implementation complete on branch `agent/executor/bb3634f87ae1`, delivery PR pending merge. All commands below ran 2026-09-08 against the delivery head (uncommitted tree identical to the PR head except this ledger record):

- `python3 -m unittest discover -s apps/chronicle/read_api -p 'test_studio_reviews_postgres.py'` — 13 tests OK (4 pre-existing updated to the 0.2 page schema + 5 new keyset/fingerprint tests; subclass re-runs included).
- `python3 -m unittest discover -s apps/chronicle/worker -p 'test_c1_t17*_unit.py'` — 19 tests OK.
- `npm --prefix apps/chronicle/webapp test` — 15 files / 43 tests passed (incl. 2 new `listReviewPage`/wrapper traversal tests).
- `npm --prefix apps/chronicle/webapp run build` — OK; `run smoke:dist` — PASS; rebuilt `apps/chronicle/web/dist/assets/studio-api.js` committed, no new asset names so `server/src/static_assets.rs` needed no change.
- `cargo test --lib` in `apps/chronicle/server` — 23 passed, incl. `vite_dist_asset_allowlist_is_complete`.
- R15 projection unit (`test_studio_reviews_r15_projection_unit.py`, pytest-style, executed directly) — 2 passed; `test_studio_entity_conflict_r19_postgres.py` — 2 tests OK (detail/decision paths untouched).
- `python3 tools/validator_ready.py --root docs/tasks/chronicle/first-round --check` — valid.

Acceptance coverage: 460 bulk items sharing one `created_at` across 2 jobs × 2 link kinds (+2 fixture reviews) paginated end-to-end with stable `(created_at, review_id)` order; cursor continued after resolving the whole front page misses nothing; cross-scope/malformed/offset/duplicate-param cursors return 400; a late row inserted before an old cursor is found at the head of a fresh read while `open_count` tracks the observed total; fingerprint is identical across pages and across decisions and rotates only on plan-membership change. `StudioReviewPage` keeps working via the `listReviews` full-page wrapper; `c1_t17_gate.py` now filters by `job_id` and follows `next_cursor`.

Not verified: full-workspace test suites outside the owned contracts (not required by the Issue); C1-T17 production gate re-run (explicitly out of scope — gate script only updated as a consumer). Post-merge reconciliation (`completion_pr`/`merge_sha`, README index, Issue close) is still required per `docs/development/task-completion.md` and must happen after the delivery PR merges.

Known residual outside this task's file ownership: `apps/chronicle/corpus/c1-t13/fixture_review.py` (historical C1 fixture driver, unreferenced by CI/workflows/acceptance/docs) still calls the retired `reviews`-array/`offset` shape. Left untouched per ownership rules; reported to the coordinator for reassignment.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-08 — Implementation complete within T09 file ownership (queue API, typed client, both test suites, gate consumer, rebuilt dist). Evidence above; delivery PR pending, post-merge reconciliation still open.
