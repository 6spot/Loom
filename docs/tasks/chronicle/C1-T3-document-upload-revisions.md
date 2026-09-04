---
task: C1-T3
issue: 492
status: in_progress
depends_on: [C1-T2]
created_at: 2026-09-04
started_at: 2026-09-04
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
- 2026-09-04 — Implementation started: additive migration
  `0003_chronicle_c1_documents.sql` (revision upload metadata + tip view),
  Python store `persistence/documents.py` (controlled .txt/.md validation,
  atomic filesystem storage under `CHRONICLE_SOURCE_DIR`, idempotent
  duplicates, active/superseded history, source locators), Studio document
  endpoints on the internal sidecar (`read_api/studio_documents.py`),
  authenticated Studio proxy routes in the Rust server (no DB driver, no
  SQL per governance), PG/filesystem integration tests, and
  `docs/documents.md`. No Loom authority change; Amendment 0006 boundary
  kept. Rust owns auth/routing, Python owns persistence.
- 2026-09-04 — Reviewer FAIL D-1 addressed: migration 0003 parks the
  0002 `forbid_revision_mutation` trigger for its own backfill UPDATE and
  re-arms it immediately; new upgrade regression test applies 0001/0002,
  inserts a live C1-T1 revision, upgrades, and proves backfill defaults,
  a still-enforced immutability guard, and clean C1-T3 appends.
- 2026-09-04 — Reviewer FAIL D-2 addressed: any non-empty declared
  Content-Type must equal the filename-derived media type (previously only
  text/plain-vs-markdown swaps were checked); HTTP regression cases plus a
  dispatch-layer absent-header test added.
- 2026-09-04 — Reviewer FAIL D-3: prior-head CI failure isolated to the
  Chrome `--dump-dom` smoke step (all contract steps green); no causal
  link to this diff found. Fix push re-runs the workflow to green.
- 2026-09-04 — Reviewer FAIL D-4 addressed: the post-commit final-publish
  path now removes the staged `.tmp-*` bytes when `os.replace` fails, so
  failed publishes cannot accumulate orphan copies; the committed row
  keeps `storage_status: missing` and the next identical upload still
  repairs it. New PG regression test injects the rename failure and
  proves cleanup + missing status + repair.
