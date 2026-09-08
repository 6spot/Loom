---
task: C2-R1-T10
issue: 560
kind: leaf
parent: C2-R1
status: planned
depends_on: [C2-R1-T04, C2-R1-T07, C2-R1-T08, C2-R1-T09]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 审核双方来源上下文、精确原文与整章查询

## Scope

[Issue #560](https://github.com/6spot/Loom/issues/560) owns the bounded implementation checklist. 审核不再只有孤立短引文；无直接Claim的人物、各候选组和两侧章节都能展开核对准确原文。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] Entity无直接Claim及mentions为空也能读取其record_sources原文。
- [ ] chapter_pair两端及batch每组/全部成员均有可访问上下文，不只首个候选。
- [ ] BOM/CRLF/非BMP、重复quote和跨章/跨revision同文均定位准确。
- [ ] 错hash/缺文件不fallback新版；匿名401，跨review anchor404；分页不静默截断。

## Verification

Not run. Implementation has not started; commands and required scenarios are in the linked Issue. Record actual commit/CI/test results here during delivery, including any unverified checks and reasons.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
