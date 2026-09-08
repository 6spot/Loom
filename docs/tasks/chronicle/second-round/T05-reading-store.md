---
task: C2-R2-T05
issue: 574
kind: leaf
parent: C2-R2
status: planned
depends_on: [C2-R2-T01, C2-R1-T19]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 阅读 stream、区段和事件位置的持久化

## Scope

[Issue #574](https://github.com/6spot/Loom/issues/574) owns the bounded implementation steps. 在 Chronicle product DB 新增不可变阅读索引和有界访问方法，复用第一轮章产物及 catalog。

Canonical contracts: [continuous reading](../../../../apps/chronicle/docs/continuous-reading.md), [reading experience](../../../../apps/chronicle/docs/reading-experience.md). Dependency and file ownership: [initiative index](README.md).

## Acceptance

- [ ] 空库经过原 migrations 加 0007 可建立表；所有新 SQL 在已注册 Chronicle 范围。
- [ ] 同输入重复调用返回同一个 stream，冲突内容不覆盖；调用方 rollback 后四表无残留。
- [ ] 读取旧 catalog 不混入未来新增 representation/stream，同 canonical ID 也不越过快照。
- [ ] 按 stream ordinal 与 event 反查有索引支持，无读出全库正文再分页的 helper。

## Verification

Not run. Implementation has not started. During delivery record actual test/CI evidence and any unavailable checks. Cross-round governance includes the first-round and second-round records as described in [task-completion](../../../development/task-completion.md#dependencies-across-initiative-directories).

## Progress Log

- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
