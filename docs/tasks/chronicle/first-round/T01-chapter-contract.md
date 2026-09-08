---
task: C2-R1-T01
issue: 551
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

# 章节联合产物 schema、原文锚点与校验器

## Scope

[Issue #551](https://github.com/6spot/Loom/issues/551) owns this bounded implementation checklist. 把已写明的章计划、联合结果、引用和 Resolution 0.2 变成机器可验证的共享合同，让后续任务使用同一套字段，不再各自设计接口。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). File ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 有效联合产物可通过；仅译文/仅 bundle/缺末段/悬空 ref/错误 kind 均拒绝。
- [ ] 重复引文 occurrence、BOM/CRLF/扩展汉字坐标正确；hash 或 chapter_id 漂移拒绝。
- [ ] 同章曹操/操共用对象的 fixture 可接受；ambiguous 不被强制配 target；公/王不成为全局别名。
- [ ] 时间源字段保留；无换算依据的公历月份拒绝；schema 与合同例子无字段冲突。

## Verification

2026-09-08 — Implementation delivered on branch `agent/executor/597a5c7340ec`, awaiting review/merge (delivery PR only; no completion claim yet):

- `python3 -m unittest discover -s apps/chronicle/persistence -p 'test_chapter_contract_unit.py' -v` — **28 tests OK** (new file `test_chapter_contract_unit.py`).
- `python3 tools/check_architecture.py` — **OK** (includes storage SQL ownership gate).
- `python3 tools/check_storage_sql_ownership.py` — **passed**.
- `git diff --check` — **clean**.
- No Postgres/DB tests: change is pure functions only (no DB, network, or model calls); no migration touched. No UI change, so no test/build/smoke:dist applies.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-08 — Implemented candidate/artifact/resolution-0.2 schemas, `chapter_contract.py` (ChapterLimits, validate/accept, anchors, resolution v0.2), `c2r1-contract` fixtures, and 28 unit tests. Focused checks listed under Verification all pass locally. Delivery PR pending review; merge_sha/completion_pr reconciliation still required post-merge per task-completion.
