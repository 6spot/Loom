---
task: C2-R1-T01
issue: 551
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

Not run. Implementation has not started; commands and required scenarios are recorded in the linked Issue. Record actual commit/CI/test results here during delivery, including any unverified checks and reasons.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
