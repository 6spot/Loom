---
task: C2-R1-T10
issue: 560
kind: leaf
parent: C2-R1
status: in_progress
depends_on: [C2-R1-T04, C2-R1-T07, C2-R1-T08, C2-R1-T09]
created_at: 2026-09-08
started_at: 2026-09-09
completed_at:
completion_pr:
merge_sha:
---

# 审核双方来源上下文、精确原文与整章查询

## Scope

[Issue #560](https://github.com/6spot/Loom/issues/560) owns the bounded implementation checklist. 审核不再只有孤立短引文；无直接Claim的人物、各候选组和两侧章节都能展开核对准确原文。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [x] Entity无直接Claim及mentions为空也能读取其record_sources原文。
- [x] chapter_pair两端及batch每组/全部成员均有可访问上下文，不只首个候选。
- [x] BOM/CRLF/非BMP、重复quote和跨章/跨revision同文均定位准确。
- [x] 错hash/缺文件不fallback新版；跨review anchor404；分页不静默截断（匿名401由Rust前置鉴权拥有，sidecar只返回只读数据）。

## Verification

2026-09-09 — Implementation on branch `agent/executor/8fe7c1662344` (delivery PR pending; no completion claim):

- `python3 -m unittest discover -s apps/chronicle/read_api -p 'test_review_source_context*.py' -v` — **26 tests OK** (19 new unit: BOM/CRLF/非BMP/重复quote/跨章跨revision/窗口400/整章16000/游标绑定/冻结成员收集；7 new PG18集成：无Claim实体record_sources可读、pair两端+batch各组/全部成员、精确窗口高亮、错hash/缺文件409无fallback、跨review anchor404、旧fixture unavailable且保留直接Claim、分页has_more/next_cursor）。
- `python3 apps/chronicle/read_api/test_studio_reviews_r15_projection_unit.py` — **PASS** (detail/decision原有投影未动）。
- `python3 -m unittest discover -s apps/chronicle/read_api -p 'test_studio_entity_conflict_r19_postgres.py' -v` — **2 tests OK**。
- `python3 -m unittest discover -s apps/chronicle/read_api -p 'test_studio_reviews_postgres.py' -v` — **13 tests OK** (T09队列回归，含detail新增source_contexts/source_entry）。
- `cargo test --manifest-path apps/chronicle/server/Cargo.toml --test server_integration` — **21 passed** (Rust通配代理未改，只读sidecar经既有/studio/jobs通配可达）。
- `git diff --check` — **clean**。
- Dependency reconciliation: T04/T07/T08/T09代码均已在本 stacked branch（含 #595/#603/#607/#591），但默认分支Task Ledger尚未全部对账完成；按Issue要求，本任务关闭须等依赖在默认分支完成对账。No UI change, so no test/build/smoke:dist applies. No new migration.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-09 — Implementation complete within T10 file ownership (source_context.py新共享解析器、studio_reviews.py详情+contexts/sources、server.py传递source_dir、两个新测试文件）。Evidence above; delivery PR pending, post-merge reconciliation still open.
