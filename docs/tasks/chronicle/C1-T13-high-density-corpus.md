---
task: C1-T13
issue: 502
status: completed
depends_on: [C1-T10, C1-T11, C1-T12]
created_at: 2026-09-04
started_at: 2026-09-05
completed_at: 2026-09-05
completion_pr: 527
merge_sha: 980ba7bd2d86494ffda7af1da797010936b525bb
---

# Chronicle First High-Density Historical Corpus

## Canonical scope

GitHub Issue #502 is the executable specification.

## Goal

Use the real Studio Book-to-Chronicle path to ingest at least five previously unprocessed complete source texts and materially densify the approximately 196–220 CE historical window.

## Acceptance

- [x] at least five complete new source texts are ingested through Studio.
- [x] before/after corpus metrics are recorded and materially exceed the C0 baseline.
- [x] representative cross-source identities/events preserve conservative merge boundaries.
- [x] sampled Claims trace to uploaded immutable source revisions.
- [x] representative new Event/Entity presentations are grounded/readable.
- [x] no accepted source uses hand-authored staged fixtures as its primary production path.
- [x] PostgreSQL/browser/Studio real-data checks pass.
- [x] known corpus gaps are documented.

## Verification

- Delivery PR #527 merged to `main` as `980ba7bd2d86494ffda7af1da797010936b525bb` on 2026-09-05.
- Chronicle PR workflow run `33933558435` completed successfully against the accepted PR merge ref on PostgreSQL 18.6 / pgvector 0.8.6. It passed persistence contracts, all 70 durable worker tests, Rust control-plane/server tests, read-model/UI/webapp contracts, two-source browser smoke, and server-front/Studio-auth smoke.
- The permanent publication-authority regressions executed in that worker suite and passed: `test_resolution_touching_inflight_bundle_is_not_published_history` and `test_staged_inflight_bundle_is_not_published_corpus_input`.
- Chronicle Docker workflow run `33933558513` completed successfully: Compose validation, clean stack startup, imported-world HTTP verification, and cleanup all passed.
- Full six-source development acceptance passed in Actions run `33932012632` rerun attempt 2. Retained artifact `c1-t13-fixture-corpus-evidence` has artifact ID `9959241697` and ZIP SHA-256 `41855c985ecc6dd312016c0ccd5c7d1764e511f7733fd66dbdd2a9af02bedc5a`.
- Final accepted corpus metrics are 6 Documents, 6 immutable Revisions, 32 chunks, 96 staged Entities, 78 staged Events, 75 staged Claims, 87 CanonicalEntities, 70 CanonicalEvents, 25 zh-CN Reader Presentations, 58 Claim-supported presentation blocks, and zero open resolution reviews.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-05 — Started from canonical `main` after C1-T12 reconciliation. The first pass audited the existing production upload/worker/model entry points before selecting the retained source pack, because T13 must exercise the same Studio Document/Revision/IngestionJob path used by the product and may fix only concrete defects discovered inside those accepted ingestion semantics.
- 2026-09-05 — Added a vendor-neutral Responses-style production model adapter and wired independent extraction/presentation model configuration into the deployed worker while preserving the no-model path for non-source test jobs. Full PostgreSQL worker regression plus Compose model configuration passed in Actions run `33895935726`.
- 2026-09-05 — Fixed a production-safety defect found by real-source pressure: immutable source jobs may no longer silently fall back to deterministic fake extraction when no extraction model is configured. Earlier T5 segmentation-only tests retain that behavior only through an explicit test seam. Full worker/source-pack/Compose regression passed in Actions run `33927154807`.
- 2026-09-05 — Frozen a six-source pinned corpus pack (`先主传`, `诸葛亮传`, `周瑜传`, `鲁肃传`, `吕蒙传`, `荀彧传`) with exact Wikisource revision IDs and uploaded-byte SHA-256 values. Real acquisition passed in Actions runs `33896918087` and `33926476461`; no accepted source uses hand-authored staged data.
- 2026-09-05 — Fixed the fresh-host source-volume ownership boundary without making long-lived Chronicle services root: Compose now runs one `chronicle-source-init` to prepare the application-owned bind mount for UID/GID 10001, and source-directory failures are surfaced as controlled persistence errors. Production-shaped Studio HTTP acceptance run `33927799041` passed: six Documents + six immutable Revisions + six queued Jobs were created, an identical second ingest reused all three identities, Studio sources/imports/API routes were readable, and staged/canonical/Reader counts remained unchanged before worker execution. Exact evidence is recorded in `apps/chronicle/corpus/c1-t13/acceptance.md` and artifact `9957452395`.
- 2026-09-05 — At the live-provider checkpoint, Actions had no configured provider credential. Rather than substitute fake staged JSON, T13 introduced a source-bound, development-only model-boundary fixture provider implementing the same extraction/presentation completion interface. Production remains fail-closed and live-provider deployment acceptance is explicitly deferred to C1-T17.
- 2026-09-05 — Complete-book pressure exposed separate segmentation and extraction prompt budgets. The T13 fixture runner now explicitly uses 32k character budgets for both boundaries without changing the 8k production defaults. It also corrected acceptance tooling to the real `needs_review -> running + cleared lease -> worker claim` resume contract.
- 2026-09-05 — Genuine resolution candidates were reviewed through the authenticated Studio API with a narrow pre-reviewed person allowlist. `曹操` and `周瑜` can receive explicit `same_entity`; same-name places remain `uncertain`. The final acceptance produced 13 resolved ReviewItems: 10 `same_entity` and 3 `uncertain` (`南郡` once, `江陵` twice), with zero open review debt.
- 2026-09-05 — Positive merges exposed a batch-publication authority defect: a merely staged bundle from another in-flight Job could enter a neighboring canonical publication before its own review completed. `resolve_publish` now separates all staged audit/storage state from the canonical-published corpus defined by the latest catalog; the Worker separately verifies its own new staged bundle. A permanent PostgreSQL regression test, `test_published_corpus_boundary_postgres.py`, locks this authority boundary. The same pressure also exposed and fixed a Worker exception handler that could mask `PublicationConflict` with `NameError`.
- 2026-09-05 — Full six-source development acceptance passed in rerun attempt 2 of Actions run `33932012632`, whose branch checkout resolved to commit `1660f760a5d17e98f476afb3b9a8dca112098669`. All six Jobs completed through structure/segment/extract/assemble/review/resolve/publish/present on PostgreSQL 18. Review convergence completed in four bounded cycles; post-publication replay created no duplicate Document, Revision or Job.
- 2026-09-05 — Final retained metrics: Documents `0 -> 6`, Revisions `0 -> 6`, chunks `0 -> 32`, staged Entities `71 -> 96`, staged Events `53 -> 78`, staged Claims `50 -> 75`, canonical Entities `66 -> 87`, canonical Events `45 -> 70`, Reader Presentations `0 -> 25`, presentation blocks/supports `0 -> 58`, open reviews `0`. All 25 frozen source-bound Claims persisted and all 58 presentation blocks have Claim support. Final catalog SHA-256 is `f93f08793d6736cd39e9cc9c2aba82360045ac074b2479c70218ff16e873e0cb`.
- 2026-09-05 — Final evidence artifact: `c1-t13-fixture-corpus-evidence`, artifact ID `9959241697`, ZIP SHA-256 `41855c985ecc6dd312016c0ccd5c7d1764e511f7733fd66dbdd2a9af02bedc5a`. Detailed source hashes, before/after metrics, review examples, grounding guarantees and known gaps are recorded in `apps/chronicle/corpus/c1-t13/acceptance.md`.
- 2026-09-05 — Implementation acceptance is satisfied, but this task intentionally remains `in_progress`: repository governance requires the delivery PR to merge first, then a canonical-main Task Ledger reconciliation with the actual PR number and merge SHA before Issue #502 may close or C1-T14 may become READY.
- 2026-09-05 — Delivery PR #527 merged to canonical `main` as `980ba7bd2d86494ffda7af1da797010936b525bb` after Chronicle run `33933558435` and Chronicle Docker run `33933558513` both passed. This reconciliation records the actual delivery evidence and marks C1-T13 completed; downstream READY eligibility is recalculated only after the reconciliation itself reaches `main`.
