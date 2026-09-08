---
task: C2-R1-T08
issue: 558
kind: leaf
parent: C2-R1
status: planned
depends_on: [C2-R1-T04, C2-R1-T07]
created_at: 2026-09-08
started_at:
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

Not run. Implementation has not started; commands and required scenarios are in the linked Issue. Record actual commit/CI/test results here during delivery, including any unverified checks and reasons.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
