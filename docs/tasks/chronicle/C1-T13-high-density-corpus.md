---
task: C1-T13
issue: 502
status: in_progress
depends_on: [C1-T10, C1-T11, C1-T12]
created_at: 2026-09-04
started_at: 2026-09-05
completed_at:
completion_pr:
merge_sha:
---

# Chronicle First High-Density Historical Corpus

## Canonical scope

GitHub Issue #502 is the executable specification.

## Goal

Use the real Studio Book-to-Chronicle path to ingest at least five previously unprocessed complete source texts and materially densify the approximately 196–220 CE historical window.

## Acceptance

- [ ] at least five complete new source texts are ingested through Studio.
- [ ] before/after corpus metrics are recorded and materially exceed the C0 baseline.
- [ ] representative cross-source identities/events preserve conservative merge boundaries.
- [ ] sampled Claims trace to uploaded immutable source revisions.
- [ ] representative new Event/Entity presentations are grounded/readable.
- [ ] no accepted source uses hand-authored staged fixtures as its primary production path.
- [ ] PostgreSQL/browser/Studio real-data checks pass.
- [ ] known corpus gaps are documented.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-05 — Started from canonical `main` after C1-T12 reconciliation. The first pass will audit the existing production upload/worker/model entry points before selecting the retained source pack, because T13 must exercise the same Studio Document/Revision/IngestionJob path used by the product and may fix only concrete defects discovered inside those accepted ingestion semantics. The source pack remains bounded around approximately 196–220 CE, must contain at least five previously unprocessed complete historical texts, and will prefer `三国志·蜀书·先主传` plus complementary Wei/Shu/Wu biographies with cross-source overlap.
- 2026-09-05 — Added a vendor-neutral Responses-style production model adapter and wired independent extraction/presentation model configuration into the deployed worker while preserving the no-model path for non-source test jobs. Full PostgreSQL worker regression plus Compose model configuration passed in Actions run `33895935726`.
- 2026-09-05 — Fixed a production-safety defect found by real-source pressure: immutable source jobs may no longer silently fall back to deterministic fake extraction when no extraction model is configured. Earlier T5 segmentation-only tests retain that behavior only through an explicit test seam. Full worker/source-pack/Compose regression passed in Actions run `33927154807`.
- 2026-09-05 — Frozen a six-source pinned corpus pack (`先主传`, `诸葛亮传`, `周瑜传`, `鲁肃传`, `吕蒙传`, `荀彧传`) with exact Wikisource revision ids and uploaded-byte SHA-256 values. Real acquisition passed in Actions runs `33896918087` and `33926476461`; no accepted source uses hand-authored staged data.
- 2026-09-05 — Fixed the fresh-host source-volume ownership boundary without making long-lived Chronicle services root: Compose now runs one `chronicle-source-init` to prepare the application-owned bind mount for UID/GID 10001, and source-directory failures are surfaced as controlled persistence errors. Production-shaped Studio HTTP acceptance run `33927799041` passed: six Documents + six immutable Revisions + six queued Jobs were created, an identical second ingest reused all three identities, Studio sources/imports/API routes were readable, and staged/canonical/Reader counts remained unchanged before worker execution. Exact evidence is recorded in `apps/chronicle/corpus/c1-t13/acceptance.md` and artifact `9957452395`.
- 2026-09-05 — Live-model execution remains the only substantive T13 acceptance blocker at this checkpoint. Actions run `33926476461` confirmed only the boolean fact `OPENAI_API_KEY available=False`; no secret value was emitted. T13 therefore remains `in_progress` and will not claim corpus-density, cross-source-resolution or Reader-Presentation acceptance from fake model output.
