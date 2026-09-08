---
task: C2-R1-T04
issue: 554
kind: leaf
parent: C2-R1
status: in_progress
depends_on: [C2-R1-T01]
created_at: 2026-09-08
started_at: 2026-09-09
completed_at:
completion_pr:
merge_sha:
---

# 章产物存储、租约写入与发布记录表

## Scope

[Issue #554](https://github.com/6spot/Loom/issues/554) owns this bounded implementation checklist. 完整译文、提取结果和引用一起接受，恢复时不会拿半份或另一个版本的结果继续。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). File ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] fresh PG18 迁移、重复执行迁移、完整产物写读成功。
- [ ] 半产物、错revision/producing-run/lease、hash冲突、重复pub不幂等问题均有负例。
- [ ] 0.1或错误scope不能同bundle；0.2受控写入可用；自反 Entity/Event link 拒绝。
- [ ] 未调用 publication helper前公共目录不可见；原 Reader Presentation Claim约束未放宽。

## Verification

2026-09-09 — Implementation on branch `agent/executor/677c2a31b8d9` (delivery PR pending; no completion claim):

- `python3 -m unittest discover -s apps/chronicle/persistence -p 'test_chapter_store_postgres.py' -v` — **17 tests OK** (was 14; +3 reviewer-driven regressions: failed-run rejection, concurrent identical accept+publish idempotency, concurrent chapter conflict surfaced as PersistenceConflict).
- `python3 -m unittest discover -s apps/chronicle/persistence -p 'test_control_plane_postgres.py' -v` — **9 tests OK** (regression; one mechanical expectation update for the new `0006` migration version).
- `python3 -m unittest apps.chronicle.persistence.test_postgres_v0` — **4 tests OK**; `test_presentation_postgres` — **8 tests OK** (migration regression: C0 + Reader Presentation paths untouched).
- `python3 tools/check_storage_sql_ownership.py` — **passed**; `git diff --check` — **clean**.
- `python3 tools/validator_ready.py --root docs/tasks/chronicle/first-round --check` — reports one `dependency eligibility` violation for this record (`in_progress` while C2-R1-T01 is still `in_progress` on the default branch). This is the expected mechanical consequence of starting per Leader dispatch before T01 reconciles to `completed` (T01 code is on main at `0b70308`, ledger still `in_progress`); the snapshot view lists T04 as blocked on the same dependency. The violation clears when T01 completes reconciliation — it must not be worked around by editing dependency metadata.
- No UI change, so no test/build/smoke:dist applies. No `control_plane.py` change was required: the chapter fence reuses `require_job_lease`; the only cross-file touch is the one-line migration-version expectation above.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-09 — Implementation started per Leader dispatch. Dependency note: C2-R1-T01 code is present on the default branch (merge `0b70308`) but its Task Ledger record is still `in_progress`, so downstream READY remains pending T01 reconciliation; this task consumes only the T01 contract code, not its completion status.
- 2026-09-09 — Reviewer CHANGES_REQUIRED on PR #595 addressed on the same branch: (1) `record_accepted_chapter_fenced` now rejects `failed` producing runs before any write, with a negative test proving both rows unchanged; (2) both race inserts are savepoint-scoped so concurrent replays stay idempotent instead of leaking `InFailedSqlTransaction`, with threaded replay + deterministic conflict tests. Both new tests were shown to fail on the pre-fix code (`InFailedSqlTransaction` reproduced) and pass after. Full suite re-run green (17 + 9 + 4 + 8).
