---
task: C2-R1-T01
issue: 551
kind: leaf
parent: C2-R1
status: completed
depends_on: []
created_at: 2026-09-08
started_at: 2026-09-08
completed_at: 2026-09-08
completion_pr: 590
merge_sha: 0b70308408088ba7ced7f183833c74fc4f005cca
---

# 章节联合产物 schema、原文锚点与校验器

## Scope

[Issue #551](https://github.com/6spot/Loom/issues/551) owns this bounded implementation checklist. 把已写明的章计划、联合结果、引用和 Resolution 0.2 变成机器可验证的共享合同，让后续任务使用同一套字段，不再各自设计接口。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). File ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [x] 有效联合产物可通过；仅译文/仅 bundle/缺末段/悬空 ref/错误 kind 均拒绝。
- [x] 重复引文 occurrence、BOM/CRLF/扩展汉字坐标正确；hash 或 chapter_id 漂移拒绝。
- [x] 同章曹操/操共用对象的 fixture 可接受；ambiguous 不被强制配 target；公/王不成为全局别名。
- [x] 时间源字段保留；无换算依据的公历月份拒绝；schema 与合同例子无字段冲突。

## Verification

2026-09-08 — Implementation delivered on branch `agent/executor/597a5c7340ec`, awaiting review/merge (delivery PR only; no completion claim yet):

- `python3 -m unittest discover -s apps/chronicle/persistence -p 'test_chapter_contract_unit.py' -v` — **42 tests OK** (new file `test_chapter_contract_unit.py`; 28 initial + 11 first-review regressions + 3 second-review regressions).
- `python3 tools/check_architecture.py` — **OK** (includes storage SQL ownership gate).
- `python3 tools/check_storage_sql_ownership.py` — **passed**.
- `git diff --check` — **clean**.
- No Postgres/DB tests: change is pure functions only (no DB, network, or model calls); no migration touched. No UI change, so no test/build/smoke:dist applies.

2026-09-08 — Post-merge reconciliation (delivery PR #590 merged as `0b70308408088ba7ced7f183833c74fc4f005cca` on 2026-09-08; GitHub Issue #551 closed by that merge):

- `python3 -m unittest discover -s apps/chronicle/persistence -p 'test_chapter_contract_unit.py'` re-run on the post-merge default branch — **42 tests OK**.
- `python3 tools/check_architecture.py` — **OK**; `python3 tools/check_storage_sql_ownership.py` — **passed**; `git diff --check` — **clean**.
- All four acceptance boxes above are satisfied by the delivered work (merged after three Reviewer rounds on PR #590); front matter reconciled with actual completion_pr/merge_sha.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-08 — Implemented candidate/artifact/resolution-0.2 schemas, `chapter_contract.py` (ChapterLimits, validate/accept, anchors, resolution v0.2), `c2r1-contract` fixtures, and 28 unit tests. Focused checks listed under Verification all pass locally. Delivery PR pending review; merge_sha/completion_pr reconciliation still required post-merge per task-completion.
- 2026-09-08 — Addressed all six Reviewer findings on PR #590 (fail-closed accept binding, malformed-type guards, global temp_id uniqueness+prefixes, cross_source distinct bundles, translation ordering, contract-complete DTO builders/validators+fixtures). Suite extended 28 → 39 tests, all passing locally; same focused checks re-run green. Pushed to the existing PR; merge/reconciliation still pending.
- 2026-09-08 — Addressed the three remaining Reviewer findings (fail-closed `_model_list` guards on every model-controlled collection/value incl. malformed request limits, `src_` prefix enforcement on source.temp_id, required `job_id` in source descriptors/builders/fixtures/validators). Suite extended 39 → 42 tests, all passing locally; same focused checks re-run green. Pushed to the existing PR; merge/reconciliation still pending.
- 2026-09-08 — Reconciled: delivery PR #590 merged (`0b70308…5cca`), Issue #551 closed, acceptance checked, verification re-run green on the post-merge branch. Task completed; reconciliation rides PR #594 to the default branch (no separate PR per coordination order).
