---
task: C1-T3
issue: 492
status: planned
depends_on: [C1-T2]
created_at: 2026-09-04
started_at:
completed_at:
completion_pr:
merge_sha:
---

# Chronicle Document Upload and Immutable Revisions

## Canonical scope

GitHub Issue #492 is the executable specification.

## Goal

Make uploaded UTF-8 historical texts durable first-class Documents/Revisions with immutable source content, hashes, locators, and non-destructive supersession.

## Acceptance

- [ ] authenticated admin can create a Document and upload `.txt`/`.md` revisions.
- [ ] original content persists through the supported Chronicle data volume.
- [ ] revision hash/metadata/storage key are deterministic and auditable.
- [ ] replacement creates a new revision and preserves the old revision.
- [ ] invalid encoding/size/path/interrupted-write cases fail safely.
- [ ] revision history and active/superseded state are queryable.
- [ ] later chunk/evidence provenance can address exact source text.
- [ ] PostgreSQL/filesystem integration checks pass.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
