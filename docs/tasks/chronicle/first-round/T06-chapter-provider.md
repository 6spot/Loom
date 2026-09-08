---
task: C2-R1-T06
issue: 556
kind: leaf
parent: C2-R1
status: planned
depends_on: [C2-R1-T01]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 真实模型与fixture适配新的联合输出协议

## Scope

[Issue #556](https://github.com/6spot/Loom/issues/556) owns the bounded implementation checklist. 生产模型实际收到章级structured-output约束和输出预算，fixture也走同一形状，避免后台仍要求旧的小块bundle。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 实际HTTP请求携带联合schema和output token限制，无程序生成offset/canonical字段。
- [ ] 正常、incomplete/length、无文本、超byte cap、运输重试耗尽全部有明确测试。
- [ ] fixture与live走相同模型candidate形状；生产配置不会静默落入fixture。
- [ ] 旧人物/事件简介provider回归不变，密钥不泄露。

## Verification

Not run. Implementation has not started; commands and required scenarios are in the linked Issue. Record actual commit/CI/test results here during delivery, including any unverified checks and reasons.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
