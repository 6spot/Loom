---
task: C2-R2-T09
issue: 578
kind: leaf
parent: C2-R2
depends_on: [C2-R2-T03, C2-R2-T07, C2-R2-T08]
created_at: 2026-09-08
---

# 统一接入 Python/Rust 公开路由和 typed 阅读 client

## Scope

[Issue #578](https://github.com/6spot/Loom/issues/578) owns the bounded implementation steps. 把已实现的阅读领域查询接入唯一公共 HTTP 边界，并提供带 snapshot、abort 和稳定 query key 的前端 client。

Canonical contracts: [continuous reading](../../../../apps/chronicle/docs/continuous-reading.md), [reading experience](../../../../apps/chronicle/docs/reading-experience.md). Dependency and file ownership: [initiative index](README.md).

## Acceptance

- [ ] 新路由从 Rust 可读且 Python 内部路径准确；公开读取不需要管理员，Studio 仍受原认证约束。
- [ ] 坏参数、非法方法、未知对象与 source 不可用错误准确返回。
- [ ] client/query cache 不仅按 canonical ID 缓存，换 snapshot 不复用错误正文/预览。
- [ ] 无需修改公共 App 或 dist 即能完成 HTTP/纯 client 交付。
- [ ] 旧详情无 catalog 行为保持；带 catalog 的 Event/Entity detail 与阅读页一致，未绑定快照的 latest presentation 不混入。
- [ ] 0.2 章的公开原文和 Studio 审核上下文均可查看，source/hash/越权拒绝不变；0.1 历史 fixture 回归保留。

## Verification requirements

Run the checks specified in the linked Issue and the current [delivery guide](../../../development/task-completion.md). Record actual acceptance, test/CI results and any unavailable checks in the delivery PR.

## Progress Log

- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
