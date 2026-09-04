---
task: C1-T3
issue: 492
status: completed
depends_on: [C1-T2]
created_at: 2026-09-04
started_at: 2026-09-04
completed_at: 2026-09-04
completion_pr: 511
merge_sha: 2dd71b7a9f2ae6aae311b9574632ab81eb4828ba
---

# Chronicle Document Upload and Immutable Revisions

## Canonical scope

GitHub Issue #492 is the executable specification.

## Goal

Make uploaded UTF-8 historical texts durable first-class Documents/Revisions with immutable source content, hashes, locators, and non-destructive supersession.

## Acceptance

- [x] authenticated admin can create a Document and upload `.txt`/`.md` revisions.
- [x] original content persists through the supported Chronicle data volume.
- [x] revision hash/metadata/storage key are deterministic and auditable.
- [x] replacement creates a new revision and preserves the old revision.
- [x] invalid encoding/size/path/interrupted-write cases fail safely.
- [x] revision history and active/superseded state are queryable.
- [x] later chunk/evidence provenance can address exact source text.
- [x] PostgreSQL/filesystem integration checks pass.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-04 — Implementation added migration `0003_chronicle_c1_documents.sql`, controlled `.txt`/`.md` validation and atomic filesystem storage, idempotent duplicate repair, active/superseded revision history and source locators, Studio document sidecar endpoints, authenticated Rust proxy routes, source-volume configuration, PG/filesystem tests and `docs/documents.md`.
- 2026-09-04 — Review findings addressed: migration upgrade temporarily parks/re-arms the prior immutable-revision trigger for backfill; declared Content-Type must match filename-derived media type; failed final publish cleans staged temp bytes and remains repairable on identical re-upload; Chrome smoke was rerun after unrelated prior-head failure isolation.
- 2026-09-04 — Delivery PR #511 merged as `2dd71b7a9f2ae6aae311b9574632ab81eb4828ba`. Exact delivery head `a9e89f4126402d8842c60db86b02a06231580ccb` passed GitHub Actions Chronicle run 33860204881, Chronicle Docker run 33860204866, and CI run 33860204864. Catch-up post-merge reconciliation records the already-delivered task as completed on the canonical ledger.
