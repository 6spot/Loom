---
task: C2-R1-T02
issue: 552
kind: leaf
parent: C2-R1
status: planned
depends_on: []
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 冻结两部著作、四个完整自然章及内容核对点

## Scope

[Issue #552](https://github.com/6spot/Loom/issues/552) owns this bounded implementation checklist. 提供真实的同书跨章、跨书对照和全文验收输入；不要求用户再找材料。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). File ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 固定四章/两部作品及所有实际版本，不再留下待选篇目。
- [ ] 重新 prepare 可重现相同 hash；三国志多章输入可证明是同一 revision，而非三个分离 job。
- [ ] 12个以上检查点都能定位到正确原文件/范围，合成负例与真实观察清楚分开。
- [ ] 超限章保留明确拒绝样例，注释和原文首尾没有被获取工具静默丢弃。

## Verification

Not run. Implementation has not started; commands and required scenarios are recorded in the linked Issue. Record actual commit/CI/test results here during delivery, including any unverified checks and reasons.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
