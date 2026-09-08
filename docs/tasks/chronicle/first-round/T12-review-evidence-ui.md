---
task: C2-R1-T12
issue: 562
kind: leaf
parent: C2-R1
status: planned
depends_on: [C2-R1-T10, C2-R1-T11]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 审核证据展开、逐组来源与整章阅读界面

## Scope

[Issue #562](https://github.com/6spot/Loom/issues/562) owns the bounded implementation checklist. 审核比较先看到两侧真实来源和上下文，各组例外能核对，展开全文不打断连续操作。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 无Claim、chapter_pair、published batch全部候选来源可检查。
- [ ] 片段到整章分页明确未完状态，点引用不跳页首，决定和例外草稿不丢。
- [ ] 相同文字不同revision可明确区别；异步迟到不串材料；恶意HTML不执行。
- [ ] 回归T11底部连审、失败保留、跳过和范围恢复仍通过。

## Verification

Not run. Implementation has not started; commands and required scenarios are in the linked Issue. Record actual commit/CI/test results here during delivery, including any unverified checks and reasons.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
