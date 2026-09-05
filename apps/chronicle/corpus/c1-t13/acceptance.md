# C1-T13 high-density corpus acceptance evidence

This file records auditable implementation evidence for GitHub Issue #502. T13 remains `in_progress` until its delivery PR is merged and the canonical Task Ledger on `main` is reconciled with the real PR number and merge SHA.

## Retained source pack

All sources are prepared from fixed Wikisource revisions by `apps/chronicle/corpus/source_pack.py`; the resulting UTF-8 bytes are uploaded through the authenticated Studio Document/Revision/IngestionJob API. No accepted source is represented by hand-authored staged JSON.

| Key | Complete source unit | Pinned revision | Bytes | SHA-256 |
| --- | --- | ---: | ---: | --- |
| `xianzhu-liubei` | 《三國志·蜀書·先主傳》 | `三國志/卷32` oldid `2583378`, section `先主 劉備` | 37,474 | `ea40a7087560fe9e693e6f81cb7d1689704f888a40b5b8a8bf7169ec272994e8` |
| `zhuge-liang` | 《三國志·蜀書·諸葛亮傳》 | `三國志/卷35` oldid `2115776`, section `諸葛亮` | 39,206 | `b35b16f8fcd3b4385cbf0b68269429104e2594931d7d230b25f8f4973d24c9f6` |
| `zhou-yu` | 《三國志·吳書·周瑜傳》 | `三國志/卷54` oldid `2387393`, section `周瑜` | 14,996 | `63db082c4e763be3b56c87cb56e2bed904af5325e9a498b07d932d3b5af1f43e` |
| `lu-su` | 《三國志·吳書·魯肅傳》 | `三國志/卷54` oldid `2387393`, section `魯肅` | 10,715 | `1550e1735f44eda7adb9bf27f4ed2cbc9c2185baf6634400140cd52ac312553d` |
| `lu-meng` | 《三國志·吳書·呂蒙傳》 | `三國志/卷54` oldid `2387393`, section `呂蒙` | 14,164 | `3d9785cd1c2353fb74663789d3f2b9c098354718312c352ad2d4b41465217a86` |
| `xun-yu` | 《三國志·魏書·荀彧傳》 | `三國志/卷10` oldid `2274279`, section `荀彧` | 23,458 | `23f14265a544a076fa3ecde76694c07a952a3b458bb0053cdeb3d2389a40bd3c` |

Pinned acquisition was exercised repeatedly. Actions run `33896918087` proved exact revision lookup, heading extraction, byte/hash stability and retained prepared-source evidence. Run `33926476461` repeated acquisition after production-provider wiring.

## Model-boundary development acceptance

Actions had no configured live-provider credential for T13. Instead of falling back to fake staged data, T13 added an explicit development-only model-boundary fixture provider. It implements the same extraction and Reader Presentation `complete(prompt) -> text` boundary as production, while the rest of the path remains real:

`immutable uploaded Revision -> structure -> semantic segmentation/context -> extraction contract validation -> assembly -> cross-source resolution -> Studio ReviewItems -> canonical publication -> zh-CN Reader Presentation -> PostgreSQL/read surfaces`.

The fixture pack is source-bound: every rule names one exact substring that must exist in the immutable prepared source bytes. The final acceptance reports model provenance as `fixture:chronicle-c1-t13-source-fixture-v1:*`. Production leaves fixture mode unset and continues to fail closed when a real immutable source has no extraction model.

Live-provider deployment acceptance is intentionally deferred to C1-T17; T13 does not claim that the fixture run measures live-model quality, latency, cost, or provider reliability.

## Production defects found by high-density corpus pressure

T13 exposed defects that unit-sized fixtures did not:

1. **Real-source fail-open extraction.** A real immutable source could reach extraction without a configured model and silently use the deterministic fake executor. Production now fails closed; the old behavior exists only behind an explicit test seam.
2. **Fresh-host source-volume ownership.** The bind-mounted source directory could be root-owned while long-lived Chronicle services run as UID/GID `10001`. Compose now uses one bounded `chronicle-source-init` step; long-lived services remain non-root.
3. **Unbounded fixture context assumptions.** Complete biographies exceeded the former 8k development fixture input assumptions. T13's fixture runner explicitly supplies 32k segmentation/extraction limits without changing production defaults.
4. **Review-resume contract mismatch in acceptance tooling.** `resume` correctly moves `needs_review -> running` and clears the lease; the next worker claims the running job. The fixture harness now tests that real contract instead of expecting `queued`.
5. **Batch publication authority leak.** A merely staged bundle from another in-flight job could be pulled into a neighboring job's canonical publication, creating a singleton canonical UUID before its own review completed. `resolve_publish` now defines the publication corpus from the latest canonical catalog, while all staged bundles remain a separate audit/storage view. The Worker independently verifies that its own new bundle is staged before publication. `apps/chronicle/worker/test_published_corpus_boundary_postgres.py` permanently locks this boundary.
6. **Publication exception masking.** The positive-merge path exposed a missing `publication_v0` name in the Worker exception handler. Publication conflicts now remain explicit fail-closed errors instead of being masked by `NameError`.

No defect was fixed by weakening Claim grounding, review vocabulary, or canonical merge semantics.

## Studio / PostgreSQL acceptance

Actions run `33927799041` used the production-shaped Compose stack with PostgreSQL 18, the Rust authenticated front and Python read/upload sidecar to validate source upload independently from worker publication. It:

1. prepared all six pinned sources;
2. started Chronicle from an empty application data directory;
3. verified retained C0 bootstrap `entities=66 events=45 relations=2`;
4. uploaded all six texts through authenticated Studio HTTP and queued six Jobs;
5. repeated the exact operation and proved Document, immutable Revision and Job reuse;
6. exercised `/studio/sources`, `/studio/imports`, `/api/v1/studio/documents` and `/api/v1/studio/jobs`;
7. proved upload/queue state alone did not mutate historical knowledge.

Evidence: run `33927799041`, artifact `c1-t13-studio-ingestion-evidence`, artifact ID `9957452395`, digest `73f5d98091c448c11f23a862064627d2f4b91d41480fec0fe2b3ed2a168ee03d`.

The repository's permanent Chronicle CI also owns browser/front smoke for public reads and authenticated Studio surfaces; the T13 delivery PR must pass that workflow before merge.

## Full six-source publication acceptance

The successful full corpus acceptance is rerun attempt 2 of Actions run `33932012632`, job `fixture-corpus-loop`. Its explicit branch checkout resolved to commit `1660f760a5d17e98f476afb3b9a8dca112098669`, which includes the published-corpus authority fix. Every functional step passed: clean Compose/PostgreSQL 18 startup, C0 bootstrap, Studio ingestion/idempotency, six source jobs, bounded review convergence, canonical publication, Reader Presentation, final PostgreSQL assertions and post-publication ingestion idempotency.

Evidence artifact:

- name: `c1-t13-fixture-corpus-evidence`
- artifact ID: `9959241697`
- ZIP SHA-256: `41855c985ecc6dd312016c0ccd5c7d1764e511f7733fd66dbdd2a9af02bedc5a`
- acceptance schema: `chronicle.c1-t13-fixture-acceptance` v0.2
- result: `passed: true`

### Before / after density

| Metric | C0 baseline | Final | Delta |
| --- | ---: | ---: | ---: |
| Documents | 0 | 6 | +6 |
| Document revisions | 0 | 6 | +6 |
| Ingestion jobs | 0 | 6 completed | +6 |
| Sections | 0 | 8 | +8 |
| Chunks | 0 | 32 | +32 |
| Chunk runs | 0 | 32 | +32 |
| Review items | 0 | 13 resolved | +13 |
| Open reviews | 0 | 0 | 0 |
| Source bundles | 2 | 8 | +6 |
| Staged Entities | 71 | 96 | +25 |
| Staged Events | 53 | 78 | +25 |
| Staged Claims | 50 | 75 | +25 |
| Resolution artifacts | 1 | 23 | +22 |
| Canonical Entities | 66 | 87 | +21 |
| Canonical Events | 45 | 70 | +25 |
| Canonical event relations | 2 | 2 | 0 |
| Reader Presentations | 0 | 25 published | +25 |
| Presentation blocks | 0 | 58 | +58 |
| Claim supports | 0 | 58 | +58 |

Latest final catalog SHA-256: `f93f08793d6736cd39e9cc9c2aba82360045ac074b2479c70218ff16e873e0cb`.

All 25 frozen source-bound fixture Claims persisted. All 32 accepted chunk runs carry the fixture extraction model provenance. Outputs contain six assembled source bundles, six source-bundle publication links, six canonical catalogs, 22 cross-source-resolution outputs and 25 Reader Presentation outputs; no `fake-pipeline-result` output was accepted.

## Conservative review inspection

The final run produced 13 durable resolution ReviewItems and converged to zero open review debt in four bounded cycles (`10 -> 2 -> 1 -> 0` newly resolved reviews per cycle).

Decision distribution:

- `same_entity`: 10 — nine reviewed `曹操 <-> 曹操` pairs and one reviewed `周瑜 <-> 周瑜` pair. These are explicit allowlisted acceptance decisions from captured left/right source records; exact-name blocking by itself never auto-merges.
- `uncertain`: 3 — `南郡` between 《吴主传》 and 《周瑜传》, plus two `江陵` pairs involving 《武帝纪》/《吴主传》 and 《鲁肃传》. They remain distinct because same-name place surfaces do not prove identical historical identity in the supplied evidence.

Representative provenance inspection confirms the review payload carries immutable Revision metadata (`document_id`, `revision_no`, source SHA-256), source titles, bundle/ref identities, left/right extracted records, candidate signals, the operator decision, rationale and confidence. For example, the accepted 曹操 pair links `wudi:ent_001` from 《魏书·武帝纪》 with the uploaded 《蜀书·先主传》 representation while preserving both source records; the 南郡 pair retains explicit uncertainty rather than collapsing the place identity.

## Claim and Reader Presentation grounding

The acceptance checker verifies every one of the 25 frozen evidence substrings exists as a persisted staged Claim from its corresponding uploaded source bundle. The final database contains 25 published `zh-CN` Reader Presentations, 58 blocks and exactly 58 Claim-support rows; zero presentation blocks are unsupported. Presentation model provenance is exclusively `fixture:chronicle-c1-t13-source-fixture-v1:present` for this development run.

Reader Presentation remains derived and non-authoritative. The fixture provider builds readable Chinese overview/source-note blocks only from the supplied canonical/source/Claim/evidence context and emits an uncertainty block when the presentation context requires it.

## Post-publication idempotency

After all six Jobs completed, the source pack was submitted through Studio again. All six operations returned the existing Document, duplicate immutable Revision and existing completed Job (`document_created=false`, `revision_duplicate=true`, `job_created=false`). No duplicate product history was created.

## Known gaps / next ownership

- This development acceptance does not substitute for a live-provider deployment test; C1-T17 owns that final Debian/provider acceptance.
- The six complete biographies are centered on the late-Han / early-Three-Kingdoms target but naturally contain material outside the approximate 196–220 CE focus. T14 coverage must make temporal/source density explicit instead of implying completeness.
- No new canonical event relation was asserted by this source-bound fixture pack; the retained corpus still has the two C0 relations. Future relations require grounded source evidence, not a growth target.
- Coverage/completeness modeling is intentionally absent here and belongs to C1-T14.
- T13 does not add semantic search, Q&A, map/territorial modeling, RBAC, or multilingual persisted presentations.

## Acceptance conclusion

The implementation acceptance for Issue #502 is satisfied: six previously unprocessed complete source units entered through the real Studio Document/Revision/IngestionJob path, produced a materially denser grounded corpus, exercised conservative positive and uncertain resolution, published stable canonical state, generated Claim-bound Reader Presentation, and remained idempotent on replay. Task completion itself still waits for delivery-PR merge and canonical main-branch Task Ledger reconciliation.
