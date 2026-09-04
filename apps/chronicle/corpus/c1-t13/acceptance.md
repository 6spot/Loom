# C1-T13 high-density corpus acceptance evidence

This file records auditable evidence for GitHub Issue #502 while the task remains `in_progress`. It does **not** declare T13 complete until the six uploaded sources have traversed real model extraction, conservative resolution/publication, and Reader Presentation.

## Retained source pack

All sources are prepared from fixed Wikisource revisions by `apps/chronicle/corpus/source_pack.py`; the resulting UTF-8 bytes are uploaded through the authenticated Studio Document/Revision/IngestionJob API. No source below is represented by a hand-authored staged fixture.

| Key | Complete source unit | Pinned revision | Bytes | SHA-256 |
| --- | --- | ---: | ---: | --- |
| `xianzhu-liubei` | 《三國志·蜀書·先主傳》 | `三國志/卷32` oldid `2583378`, section `先主 劉備` | 37,474 | `ea40a7087560fe9e693e6f81cb7d1689704f888a40b5b8a8bf7169ec272994e8` |
| `zhuge-liang` | 《三國志·蜀書·諸葛亮傳》 | `三國志/卷35` oldid `2115776`, section `諸葛亮` | 39,206 | `b35b16f8fcd3b4385cbf0b68269429104e2594931d7d230b25f8f4973d24c9f6` |
| `zhou-yu` | 《三國志·吳書·周瑜傳》 | `三國志/卷54` oldid `2387393`, section `周瑜` | 14,996 | `63db082c4e763be3b56c87cb56e2bed904af5325e9a498b07d932d3b5af1f43e` |
| `lu-su` | 《三國志·吳書·魯肅傳》 | `三國志/卷54` oldid `2387393`, section `魯肅` | 10,715 | `1550e1735f44eda7adb9bf27f4ed2cbc9c2185baf6634400140cd52ac312553d` |
| `lu-meng` | 《三國志·吳書·呂蒙傳》 | `三國志/卷54` oldid `2387393`, section `呂蒙` | 14,164 | `3d9785cd1c2353fb74663789d3f2b9c098354718312c352ad2d4b41465217a86` |
| `xun-yu` | 《三國志·魏書·荀彧傳》 | `三國志/卷10` oldid `2274279`, section `荀彧` | 23,458 | `23f14265a544a076fa3ecde76694c07a952a3b458bb0053cdeb3d2389a40bd3c` |

Pinned acquisition was exercised repeatedly. GitHub Actions run `33896918087` proved exact revision lookup, heading extraction, byte/hash stability and retained a seven-file prepared-source artifact. Run `33926476461` repeated the acquisition after production-provider wiring and also passed.

## Production model/control-plane defects found by real corpus pressure

T13 found two defects that unit-sized C1 fixtures did not expose:

1. A real immutable source could proceed through real structure/segmentation and then fall back to the deterministic fake extraction executor when no extraction model was configured. Production now fails closed by default. The fake-after-real-source path is available only through an explicit test-only `allow_fake_after_real_source=True` seam used by earlier segmentation-stage isolation tests. GitHub Actions run `33927154807` passed the complete worker regression suite plus the new real-source fail-closed PostgreSQL test.
2. Fresh Debian/CI bind-mounted source directories were root-owned while Chronicle long-lived containers run as UID/GID `10001`. The first Studio revision upload therefore failed behind the Rust proxy. Compose now uses a one-shot root `chronicle-source-init` to prepare/chown only the application-owned source volume; `chronicle-read` and `chronicle-worker` remain non-root. Storage directory creation failures are also translated to `PersistenceError` rather than tearing down the sidecar connection.

## Real Studio HTTP ingestion acceptance

GitHub Actions run `33927799041` used the production-shaped Compose stack, PostgreSQL 18, the Rust authenticated web front and the Python read/upload sidecar. The worker profile was deliberately **not** started for this acceptance so Document/Revision/Job creation could be verified independently of historical-publication authority.

The run:

1. prepared all six pinned sources;
2. started Chronicle from an empty application data directory;
3. verified retained C0 bootstrap `entities=66 events=45 relations=2`;
4. captured a baseline density snapshot;
5. uploaded all six texts through authenticated Studio HTTP and queued six ingestion jobs;
6. repeated the exact same operator action and proved Document, immutable Revision and Job reuse rather than duplication;
7. exercised `/studio/sources`, `/studio/imports`, `/api/v1/studio/documents` and `/api/v1/studio/jobs`;
8. captured the queued-after density snapshot;
9. proved that merely uploading/queuing sources does not mutate staged/canonical historical knowledge or Reader Presentation.

Evidence artifact: Actions run `33927799041`, artifact `c1-t13-studio-ingestion-evidence`, artifact ID `9957452395`, ZIP digest `73f5d98091c448c11f23a862064627d2f4b91d41480fec0fe2b3ed2a168ee03d`.

### Baseline

```text
Documents              0
Document revisions     0
Ingestion jobs          0
Source bundles          2
Staged entities        71
Staged events          53
Staged claims          50
Resolution artifacts    1
Canonical entities     66
Canonical events       45
Event relations         2
Reader presentations    0
```

Latest retained catalog in that run: `1881a9c7a8a016bdd5f63cbe7a19514088c17a2418c5a0abd227bb1a1a482b9a`.

### After Studio upload/queue, before worker execution

```text
Documents              6   (+6)
Document revisions     6   (+6)
Ingestion jobs          6   (+6, all queued)
Source bundles          2   (unchanged)
Staged entities        71   (unchanged)
Staged events          53   (unchanged)
Staged claims          50   (unchanged)
Resolution artifacts    1   (unchanged)
Canonical entities     66   (unchanged)
Canonical events       45   (unchanged)
Event relations         2   (unchanged)
Reader presentations    0   (unchanged)
```

The unchanged historical counts are required at this checkpoint: Studio upload/job control-plane state is not historical publication authority.

## Live-model acceptance status

A branch-only credential probe in Actions run `33926476461` printed only the boolean availability result and confirmed `OPENAI_API_KEY available=False`. No credential value was emitted or persisted. Therefore the task must not substitute deterministic fake extraction and must not claim the final corpus-density acceptance yet.

The production worker is already wired to a vendor-neutral Responses-style endpoint through:

- `CHRONICLE_MODEL_ENDPOINT`
- `CHRONICLE_MODEL_API_KEY`
- `CHRONICLE_EXTRACTION_MODEL`
- `CHRONICLE_PRESENTATION_MODEL`

The remaining T13 gate is to run the six queued immutable revisions through a real configured model provider, handle any conservative ReviewItems, publish through the existing C0 resolution/canonical authority, generate Claim-bound `zh-CN` Reader Presentation, and capture the final before/after density plus representative provenance traces.

## Known gaps while T13 remains open

- No final denser canonical corpus is accepted until real model execution occurs.
- No cross-source merge quality claim is accepted from source-upload counts alone.
- No new Reader Presentation is accepted until every sampled block resolves to persisted Claim/Evidence/Source support.
- Coverage is intentionally not implemented here; C1-T14 owns the coverage model after T13 completes.
