---
task: C2-R1-T14
issue: 564
kind: leaf
parent: C2-R1
status: planned
depends_on: [C2-R1-T10, C2-R1-T13]
created_at: 2026-09-08
started_at:
completed_at:
completion_pr:
merge_sha:
---

# 公开章节目录、完整译文与版本固定的原文API

## Scope

[Issue #564](https://github.com/6spot/Loom/issues/564) owns the bounded implementation checklist. 读者能发现已发布章节、获取真正全文，并且每次核对都回到同一个publication对应的原文版本。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [x] 未发布产物和原文public请求404，目录没有私有revision泄漏。
- [x] 整章首尾与全部无Claim译文段可读；多对多引用位置正确。
- [x] 跨版本/跨publication引用404或明确错误，source hash漂移不读新版。
- [x] 所有GET只读且不触发模型，完整publication的正文/原文/对象映射一致。

## Verification

2026-09-09 — Implemented on `agent/executor/b9d1c24da137` (delivery PR pending):

- `python3 -m unittest discover -s apps/chronicle/read_api -p 'test_reader_chapters_postgres.py' -v` — **14 tests OK** (PG18 isolated DBs: published-only stable directory + limit=1 cursor walk, full detail incl. claim-less blocks + many-to-many ref positions + T01 validator pass, unknown/malformed publication 404, cross-publication anchors 404 both directions, old-revision pinning incl. R1-only quote + highlight, hash-drift 409 source_mismatch with detail still serving stored text, missing-file 409 source_unavailable, exact chapter reassembly via limit=7 paging, 400/405 codes, read-only proof over 5 write-side tables, unmapped-ref 409 reference_unmapped, **same-job second assembled output isolation** — old directory titles/detail refs/sources pinned to the old bundle, **tampered-bundle 409 reference_unavailable**).
- `python3 apps/chronicle/read_api/test_reader_chapters_unit.py` — **8 tests OK** (cursor round-trip/scope binding, 8 MiB cap explicit failure, 405/404 without DB).
- `python3 -m unittest discover -s apps/chronicle/read_api -p 'test_reader_presentation*.py' -v` — **2 tests OK** (Issue-required regression).
- T10/T09 regression (shared router/server paths): `test_review_source_context*.py` — **35 OK**; `test_studio_reviews_postgres.py` — **13 OK**; R15 projection — **PASS**; R19 — **2 OK**; `test_server_static.py` — **3 OK**.
- `git diff --check` — **clean**.
- Dependency reconciliation: T10 (#608) + T13 (#609) code merged on default branch; per Leader direction and `task-completion.md` (Task Ledger non-authoritative since #604), code-merge satisfies the dependency — no ledger backfill manufactured.
- No Rust/App/dist change (T17 owns the frontend mapping); no new migration.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-09 — Implemented within T14 file ownership (`reader_chapters.py` new, `router.py` chapters mount, `server.py` storage_dir injection, `test_reader_chapters_postgres.py` + `test_reader_chapters_unit.py` new, `read-api.md` public-chapters section). Evidence above; delivery PR pending, Reviewer review still open.
- 2026-09-09 — Reviewer CHANGES_REQUIRED addressed on the same branch: `_load_assembled_output()` now binds the publication's exact `assembled_bundle_sha256` (`artifact_sha256` equality, no `created_at DESC` latest-row read) and verifies the stored payload/bundle hash before use; directory + detail both pass the per-publication hash through. Two new regression tests (second assembled output isolation, tampered-bundle explicit failure). Full battery re-run green (see Verification); PR updated, awaiting re-review.
