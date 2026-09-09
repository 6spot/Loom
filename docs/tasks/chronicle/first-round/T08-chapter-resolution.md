---
task: C2-R1-T08
issue: 558
kind: leaf
parent: C2-R1
status: in_progress
depends_on: [C2-R1-T04, C2-R1-T07]
created_at: 2026-09-08
started_at: 2026-09-09
completed_at:
completion_pr:
merge_sha:
---

# 同书跨章候选、混合审核计划与发布器版本适配

## Scope

[Issue #558](https://github.com/6spot/Loom/issues/558) owns the bounded implementation checklist. 同一revision的不同章也能有依据地审核身份；全部决定进入同一最终图，避免书内same-link只停留在assembly报告中。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 同书A/B两章曹操候选能审核并由原union规则发布为同一identity；同名无充分依据仍可uncertain。
- [ ] 一个job混合chapter_pair和published_batch，全部candidate恰好覆盖一次；错mode/组/重复或漏候选拒绝。
- [ ] 跨章same链桥接两个已发布ID时拒绝；not_same/related/uncertain不误合并。
- [ ] 同plan恢复不重复债务；0.2来源hash与canonical event relation provenance一致。

## Verification

2026-09-09 — Implementation on branch `agent/executor/c8ce89c3b323` (delivery PR pending; no completion claim):

- `python3 -m unittest discover -s apps/chronicle/persistence -p 'test_resolve_publish_unit.py' -v` — **33 tests OK** (was 24; +9 chapter-path tests: within-bundle blocking/uncertainty, mixed plan exact-once coverage, mode/group/duplicate rejection, fingerprint stability + tamper evidence, union merge vs uncertain-distinct, downgrade refusal, self-link ban).
- `python3 -m unittest discover -s apps/chronicle/persistence -p 'test_*review*_unit.py' -v` — **35 tests OK** (was 24; +11 new `test_review_subjects_chapter_unit.py`: per-candidate pair subjects, pair-only fan-out, mixed coexistence, legacy-mix rejection, bridge rejection via `canonical_identity_conflict`, not_same bridge break).
- `python3 -m unittest discover -s apps/chronicle/ingestion/prototype -p 'test_resolution_v0.py' -v` — **7 tests OK**; `-p 'test_publication_v0.py'` — **11 tests OK** (legacy envelopes unchanged).
- `python3 -m unittest discover -s apps/chronicle/persistence -p 'test_chapter_store_postgres.py'` — **17 tests OK** (regression: 0006 envelope + Reader constraint untouched).
- Live PG18 scope check (isolated database, migrations applied): `0.2`/`within_revision` persists with scope stored, legacy `0.1` cross-source persists with NULL scope, `0.1` same-bundle rejected — **passed**.
- `git diff --check` — **clean**.
- Dependency reconciliation: C2-R1-T04 ledger is `in_progress` and C2-R1-T07 ledger is `planned` on the default branch (`main` contains neither merge); both code merges exist only on the stacked branch. Per the Issue, this task **cannot close** until T04/T07 reconcile to `completed` on the default branch. No UI change, so no test/build/smoke:dist applies. No new migration; `ingestion_worker.py` untouched.

2026-09-09 — Reviewer CHANGES_REQUIRED on PR #607 (head `d17b3ac`) addressed on the same branch:

- 冻结计划恢复精确校验：fingerprint 新增 `pair_candidate_keys` 绑定；`validate_chapter_review_plan` 在 fingerprint 之外逐项核对 `pair_payloads`（mode/指纹/单候选/决议号/左右端/signals/词表）与 `batch_payloads`（mode/指纹/覆盖/组-成员一致），缺失或篡改 fail closed；`open_chapter_review_plan` 要求计划携带 `candidate_keys` 并强制 payload 恰好覆盖一次。6 个新篡改/漏项测试在修复前代码上失败 5 项（已用旧版模块实测复现），修复后全部通过。
- 0.2/scope 非法组合门禁：publisher 拒绝 `within_revision` 配不同 bundle、`cross_source` 配相同 bundle、0.1 带 scope、0.1 同 bundle；store 拒绝 0.1 带 scope（`cross_source` 同 bundle 亦拒绝）。新增 4 个组合拒绝测试。
- within-bundle 改按 `(chapter_index, ref)` 定序：`build_within_bundle_candidate_set` 新增可选 `chapter_index_by_id`（assembly plan 章序），缺项 fail closed；章路径透传该映射。新增哈希 chapter_id 反序测试（字符串序与引用序均与章序相反，仍以章序为准）。

复测（均为真实运行）：`test_resolve_publish_unit.py` — **40 tests OK**（+7）；`test_*review*_unit.py` — **41 tests OK**（+6）；`test_resolution_v0.py` — **7 OK**；`test_publication_v0.py` — **11 OK**；`test_chapter_store_postgres.py` — **17 OK**（回归）；`git diff --check` — **clean**。

2026-09-09 — Reviewer 第二轮 CHANGES_REQUIRED（head `a248205`）在原 PR 同分支修复：

- 冻结全部字段逐项对照：fingerprint 新增 `chapter_by_ref` 与冻结构体哈希（`subjects_sha256`）绑定，计划持久化 `chapter_by_ref`；新增 `_check_plan_internal_consistency`——每个存储 payload 必须与冻结构体重建的期望 payload 完全相等（含 `members`、`review_subject_id`、groups、signals），并恰好覆盖 `candidate_keys`；`validate_chapter_review_plan` 在此之外把 pair subjects 与 within 候选重建对照、batch subject 成员与 cross 候选逐项对照、重验章差异规则；`open_chapter_review_plan` 开库前强制执行同一完整内部校验。8 个新篡改测试（batch/pair 成员端点、`review_subject_id`、batch signals/subject 成员，覆盖 validate 与 open）在修复前代码上实测失败 8 项，修复后全部通过。
- 章序强制：`chapter_index_by_id` 在 `build_within_bundle_candidate_set` 与章路径 wrappers 改为必填，无映射（缺参 TypeError、显式 None PersistenceError/ResolutionV0Error）fail-closed，不再回退按引用排序。新增缺映射拒绝测试。
- 复测（均为真实运行）：`test_resolve_publish_unit.py` — **41 tests OK**（+1）；`test_*review*_unit.py` — **49 tests OK**（+8）；`test_resolution_v0.py` — **7 OK**；`test_publication_v0.py` — **11 OK**；`test_chapter_store_postgres.py` — **17 OK**（回归）；`git diff --check` — **clean**。

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-09 — Implementation started per Leader dispatch on `agent/executor/c8ce89c3b323`. Dependency note: C2-R1-T04/T07 code is present on the stacked branch but neither Task Ledger is `completed` on the default branch, so close-out remains blocked on their reconciliation; this task consumes only their contract code, not their completion status.
