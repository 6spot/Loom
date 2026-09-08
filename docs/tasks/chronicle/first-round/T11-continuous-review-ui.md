---
task: C2-R1-T11
issue: 561
kind: leaf
parent: C2-R1
status: planned
depends_on: [C2-R1-T09]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 保存并下一项、暂时跳过、草稿和队列位置恢复

## Scope

[Issue #561](https://github.com/6spot/Loom/issues/561) owns the bounded implementation checklist. 在长审核页底部直接完成并进入下一项；失败不丢草稿，返回不丢范围和阅读位置。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 在长页最底部能保存并下一项，无需滚回顶部；返回队列保持scope/位置。
- [ ] 450项翻页、两tab竞争、晚提交新项、最后一项/只剩跳过项行为符合合同。
- [ ] Entity→Event、A组→B组不串草稿；失败刷新草稿保留，明确成功才前進。
- [ ] 暂时跳过仍open并阻塞resume；明确uncertain才提交；已处理记录不覆盖。

## Verification

Not run. Implementation has not started; commands and required scenarios are in the linked Issue. Record actual commit/CI/test results here during delivery, including any unverified checks and reasons.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
