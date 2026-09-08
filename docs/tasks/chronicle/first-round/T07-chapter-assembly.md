---
task: C2-R1-T07
issue: 557
kind: leaf
parent: C2-R1
status: planned
depends_on: [C2-R1-T01, C2-R1-T03]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 章产物组装、统一ref映射与来源provenance

## Scope

[Issue #557](https://github.com/6spot/Loom/issues/557) owns the bounded implementation checklist. 多章联合产物汇成一个revision级staged bundle，译文、提取对象、事件和原文锚点使用完全一致的ref映射。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 不同章都叫ent_001也不会冲突；跨类型所有ref均闭合。
- [ ] 译文block和mentions映射后仍指向正确章对象，原文anchor不串章。
- [ ] 缺章/多章/混revision/未accepted均失败；相同输入字节稳定。
- [ ] 章内共享对象不重复拆出；跨章同名保持独立表示，source数量不会按章膨胀。

## Verification

Not run. Implementation has not started; commands and required scenarios are in the linked Issue. Record actual commit/CI/test results here during delivery, including any unverified checks and reasons.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
