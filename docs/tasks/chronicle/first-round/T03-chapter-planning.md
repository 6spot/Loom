---
task: C2-R1-T03
issue: 553
kind: leaf
parent: C2-R1
status: planned
depends_on: [C2-R1-T01, C2-R1-T02]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 自然章规划与规范化原文 block manifest

## Scope

[Issue #553](https://github.com/6spot/Loom/issues/553) owns this bounded implementation checklist. 让整篇传记和含小标题的自然章始终作为一个理解单元，提供可恢复、可验证的完整范围。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). File ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] T02三国志输入恰好得到三章；每章覆盖其完整原文本。
- [ ] 诸葛亮原文作为单篇txt时不会被内部书信标题切成多次提取（额外回归）。
- [ ] BOM/CRLF/扩展汉字、前言、空白、嵌套标题均能准确重建范围。
- [ ] 同输入/版本得到相同计划和hash；超限整章返回明确不支持，原文未丢。

## Verification

Not run. Implementation has not started; commands and required scenarios are recorded in the linked Issue. Record actual commit/CI/test results here during delivery, including any unverified checks and reasons.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
