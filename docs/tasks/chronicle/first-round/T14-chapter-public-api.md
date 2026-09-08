---
task: C2-R1-T14
issue: 564
kind: leaf
parent: C2-R1
status: planned
depends_on: [C2-R1-T10, C2-R1-T13]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 公开章节目录、完整译文与版本固定的原文API

## Scope

[Issue #564](https://github.com/6spot/Loom/issues/564) owns the bounded implementation checklist. 读者能发现已发布章节、获取真正全文，并且每次核对都回到同一个publication对应的原文版本。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 未发布产物和原文public请求404，目录没有私有revision泄漏。
- [ ] 整章首尾与全部无Claim译文段可读；多对多引用位置正确。
- [ ] 跨版本/跨publication引用404或明确错误，source hash漂移不读新版。
- [ ] 所有GET只读且不触发模型，完整publication的正文/原文/对象映射一致。

## Verification

Not run. Implementation has not started; commands and required scenarios are in the linked Issue. Record actual commit/CI/test results here during delivery, including any unverified checks and reasons.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
