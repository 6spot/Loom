---
task: C2-R1-T16
issue: 566
kind: leaf
parent: C2-R1
status: planned
depends_on: [C2-R1-T02, C2-R1-T04, C2-R1-T06]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 空语料初始化、配置与第一轮CI路径覆盖

## Scope

[Issue #566](https://github.com/6spot/Loom/issues/566) owns the bounded implementation checklist. 真正用空开发环境开始，默认部署不暗中导入旧C0人物；新语料/合同/任务记录的变更也会触发正确CI。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 新空目录启动后无旧C0 canonical数据，迁移/重复启动成功，public空态和Studio鉴权正常。
- [ ] 显式C0回归仍可独立运行；migration-only与artifact导入互斥/参数错误明确。
- [ ] provider预算配置从env传到现worker服务，没有秘密写进仓库。
- [ ] corpus-only/ledger-only/schema-only变更触发正确检查，新测试确实运行；退休工作流不复活。

## Verification

Not run. Implementation has not started; commands and required scenarios are in the linked Issue. Record actual commit/CI/test results here during delivery, including any unverified checks and reasons.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
