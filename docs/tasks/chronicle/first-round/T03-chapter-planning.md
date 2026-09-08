---
task: C2-R1-T03
issue: 553
kind: leaf
parent: C2-R1
status: completed
depends_on: [C2-R1-T01, C2-R1-T02]
created_at: 2026-09-08
started_at: 2026-09-08
completed_at: 2026-09-08
completion_pr: 594
merge_sha: 88f3dbcae51cae1d468c228428b6037110352828
---

# 自然章规划与规范化原文 block manifest

## Scope

[Issue #553](https://github.com/6spot/Loom/issues/553) owns this bounded implementation checklist. 让整篇传记和含小标题的自然章始终作为一个理解单元，提供可恢复、可验证的完整范围。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). File ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [x] T02三国志输入恰好得到三章；每章覆盖其完整原文本。
- [x] 诸葛亮原文作为单篇txt时不会被内部书信标题切成多次提取（额外回归）。
- [x] BOM/CRLF/扩展汉字、前言、空白、嵌套标题均能准确重建范围。
- [x] 同输入/版本得到相同计划和hash；超限整章返回明确不支持，原文未丢。

## Verification

2026-09-08 — Implemented on branch `agent/executor/b90fdd0cb76a` (delivery PR only; no completion claim yet):

- `python3 -m unittest discover -s apps/chronicle/persistence -p 'test_chapter_plan_unit.py' -v` — **30 tests OK** (new file `test_chapter_plan_unit.py`).
- `python3 -m unittest discover -s apps/chronicle/persistence -p 'test_segmentation_unit.py' -v` — **OK, no regression** (C1 module untouched).
- `python3 tools/check_architecture.py` — **OK** (includes storage SQL ownership gate).
- `python3 tools/check_storage_sql_ownership.py` — **passed**.
- `git diff --check` — **clean**.
- No Postgres/DB tests: change is pure functions only (no DB, network, or model calls); no migration touched. No UI change, so no test/build/smoke:dist applies.

2026-09-08 — Post-merge reconciliation (delivery PR #594 squash-merged as `88f3dbcae51cae1d468c228428b6037110352828` on 2026-09-08; that merge also carried the T01/T02 completion-ledger reconciliation, so all T03 dependencies read `completed` on the default branch):

- `python3 tools/validator_ready.py --root docs/tasks/chronicle/first-round --check --format json` on the post-merge default branch — **valid: true, violations: []**, T03 listed READY.
- Re-ran on the post-merge branch: `test_chapter_plan_unit.py` — **30 tests OK** (三章 exactness + full-text coverage vs ingest-manifest, txt letter-title regression, BOM/CRLF/扩展汉字 code points, preface/blank/nested reconstruction, determinism + plan_sha256 recomputation, whole-chapter over-limit incl. the real rejected sample); `test_segmentation_unit.py` — **38 tests OK** (no regression); `test_chapter_contract_unit.py` — **42 tests OK**; `test_first_round_pack.py` — **11 tests OK**.
- `python3 tools/check_architecture.py` — **OK**; `python3 tools/check_storage_sql_ownership.py` — **passed**; `git diff --check` — **clean**.
- All four acceptance boxes above are satisfied by the delivered work; front matter reconciled with actual completion_pr/merge_sha. GitHub Issue #553 was auto-closed by the delivery merge; T02's Issue #552 close follows its own (already reconciled) completion ordering.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-08 — Started implementation. Dependency note: T01/T02 delivery PRs (#590/#589) are merged on the default branch and their code (chapter_contract.py, first-round corpus) is consumed here, but their Task Ledger records still read `in_progress`/`planned` (reconciliation pending), so downstream READY eligibility for T03 remains blocked until the coordinators reconcile. Implemented `chapter_plan.py` (frozen txt/md entries, absolute code-point blocks, contract chapter_id formula, whole-chapter capacity rejection, T01 request builder), 30 unit tests, and the `segmentation.md` C1-vs-planner section. Own task record only; shared index left to the coordinator.
- 2026-09-08 — Reconciled: delivery PR #594 merged (`88f3dbc…2828`); T01/T02 already `completed` on the default branch via the same merge; acceptance checked; verification re-run green on the post-merge branch. Task completed; reconciliation rides a ledger-only follow-up to the default branch per task-completion.
