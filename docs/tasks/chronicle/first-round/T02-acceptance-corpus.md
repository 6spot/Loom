---
task: C2-R1-T02
issue: 552
kind: leaf
parent: C2-R1
status: completed
depends_on: []
created_at: 2026-09-08
started_at: 2026-09-08
completed_at: 2026-09-08
completion_pr: 589
merge_sha: 2c4106787d340dbc480420c182d891d22e5af5f4
---

# 冻结两部著作、四个完整自然章及内容核对点

## Scope

[Issue #552](https://github.com/6spot/Loom/issues/552) owns this bounded implementation checklist. 提供真实的同书跨章、跨书对照和全文验收输入；不要求用户再找材料。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). File ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [x] 固定四章/两部作品及所有实际版本，不再留下待选篇目。
- [x] 重新 prepare 可重现相同 hash；三国志多章输入可证明是同一 revision，而非三个分离 job。
- [x] 12个以上检查点都能定位到正确原文件/范围，合成负例与真实观察清楚分开。
- [x] 超限章保留明确拒绝样例，注释和原文首尾没有被获取工具静默丢弃。

## Verification

2026-09-08 — Delivered by PR #589 (merged as `2c4106787d340dbc480420c182d891d22e5af5f4` on 2026-09-08), as reported in that PR:

- `python3 -m unittest discover -s apps/chronicle/corpus -p 'test_first_round_pack.py' -v` — **11 tests OK** (frozen chapters/works/revisions, re-prepare reproducibility, deterministic ingest hash/range derivation incl. single-revision proof, 13 real + 1 synthetic checkpoints, capacity gate with head/tail/commentary intactness).
- `python3 -m unittest discover -s apps/chronicle/corpus -p 'test_source_pack_unit.py'` — **7 tests OK** (no regression).
- prepare re-fetch byte-identical to prepared.json (network evidence from the delivery PR; not repeated here).
- `git diff --check` — 乾淨.

2026-09-08 — Post-merge reconciliation: re-ran both suites on the post-merge default branch — **11 tests OK** (`test_first_round_pack.py`) and **7 tests OK** (`test_source_pack_unit.py`); `cases.json` confirmed 13 real + 1 synthetic entries. All four acceptance boxes above are satisfied by the delivered work. Front matter reconciled with actual completion_pr/merge_sha. GitHub Issue #552 remains open pending this reconciliation reaching the default branch; no second PR is opened for the ledger change per coordination order.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-08 — Implemented and merged via PR #589 (frozen two-work/four-chapter corpus, ingest derivation, cases, scale report, rejection sample). Reconciled: acceptance checked, verification evidence recorded, front matter completed. Task completed; reconciliation rides PR #594 to the default branch (no separate PR per coordination order).
