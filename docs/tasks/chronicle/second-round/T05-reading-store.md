---
task: C2-R2-T05
issue: 574
kind: leaf
parent: C2-R2
depends_on: [C2-R2-T01, C2-R1-T19]
created_at: 2026-09-08
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

## Verification requirements

Run the checks specified in the linked Issue and the current [delivery guide](../../../development/task-completion.md). Record actual acceptance, test/CI results and any unavailable checks in the delivery PR.

## Progress Log

- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
- 2026-09-11 — Implemented `0007_chronicle_reading_streams.sql`, `reading_store.py` and `test_reading_store_postgres.py`; documented the store in `apps/chronicle/docs/persistence.md`. Focused PG18 run: 11/11 reading-store tests pass, storage SQL ownership check passes, chapter/control-plane/presentation/document/v0 suites still pass. Worker wiring (T06) and read APIs (T07/T08) remain downstream.
- 2026-09-11 — Review fixes: replay now compares a `content_sha256` over the complete normalized input (unit/group/occurrence/publication bindings), the chapter publication's `catalog_sha256` is bound to `origin_catalog_sha` in both the store pre-check and the stream binding trigger, and `read_reading_unit` accepts and enforces `snapshot_catalog_sha`. Added regression tests. Focused PG18 run: 13/13 reading-store tests pass; chapter/control-plane/presentation/document/v0/migrate suites still pass.
