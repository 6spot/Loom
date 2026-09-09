---
task: C2-R1-T05
issue: 555
kind: leaf
parent: C2-R1
status: in_progress
depends_on: [C2-R1-T01, C2-R1-T03]
created_at: 2026-09-08
started_at: 2026-09-09
completed_at:
completion_pr:
merge_sha:
---

# 完整章联合翻译与提取、完整上下文修正

## Scope

[Issue #555](https://github.com/6spot/Loom/issues/555) owns the bounded implementation checklist. 在同一完整章节上下文中同时得到全文白话和可定位的结构信息，任何一部分失败都不接受。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 完整章传入每一轮调用；章尾信息确实在输入中，不只前200字上下文。
- [ ] 合法整份结果一次接受；缺正文/缺引用/只结构等两轮后整体失败，保留失败记录。
- [ ] 输入/输出超限不截断且不回退chunk；修正次数及运输重试有清楚区别。
- [ ] 同章ref共享、歧义/时间/嵌注合同fixture通过；机械通过不被宣传为内容正确率。

## Verification

2026-09-09 — Implemented on branch `agent/executor/1451f4a574ff` (delivery PR only; no completion claim yet):

- Dependency reconciliation on the default branch: T01 `completed` (PR #590 / `0b70308`), T03 `completed` (PR #594 / `88f3dbc`); validator lists T05 READY.
- `python3 -m unittest discover -s apps/chronicle/persistence -p 'test_chapter_extraction_unit.py' -v` — **24 tests OK** (new files `chapter_prompt.py`, `chapter_extraction.py`, `test_chapter_extraction_unit.py`; fake `complete(prompt)->str` covers all branches).
- `python3 -m unittest discover -s apps/chronicle/persistence -p 'test_extraction_unit.py' -v` — **32 tests OK, no regression** (C1 module untouched).
- `python3 -m unittest discover -s apps/chronicle/persistence -p 'test_chapter_contract_unit.py'` — **42 tests OK**; `test_chapter_plan_unit.py` — **30 tests OK** (T01/T03 consumers unaffected).
- `python3 tools/check_architecture.py` — **OK**; `python3 tools/check_storage_sql_ownership.py` — **passed**; `git diff --check` — **clean**.
- No Postgres/DB tests: change is pure functions only (no DB, network, or model calls); no migration touched. No UI change, so no test/build/smoke:dist applies.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-09 — Started implementation. Dependencies T01/T03 verified `completed` on the default branch (ledger reconciliation, not just PR/Issue state). Implemented `chapter_prompt.py` (`c2r1-chapter-prompt-v1`: whole-chapter rendering with tail, C0 rules, bounded diagnostics), `chapter_extraction.py` (`c2r1-extraction-v1`: initial + at most one whole-chapter correction via T01 validator, typed failures, replayable history), 24 unit tests, and the `extraction.md` whole-chapter section. Own task record only; shared index left to the coordinator. Delivery PR pending review; merge_sha/completion_pr reconciliation still required post-merge per task-completion.
