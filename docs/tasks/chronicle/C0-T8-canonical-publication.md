---
task: C0-T8
issue: 470
status: completed
depends_on: [C0-T7]
created_at: 2026-09-01
started_at: 2026-09-01
completed_at: 2026-09-01
---

# Chronicle Canonical Publication v0

## Goal

Add Chronicle's first deterministic canonical publication layer above source-owned staged bundles and C0-T7 Resolution Links.

Publication assigns stable program-generated UUIDv7 identities to cross-source Entity/Event representation groups while preserving source records, source Claims, and Resolution Links unchanged.

## Architecture

```text
staged source bundles
        +
resolution links
        +
optional existing canonical catalog
        ↓
canonical publication
        ↓
CanonicalEntity / CanonicalEvent membership
        +
related canonical Event relations
```

Publication is model-free and human-gold-free.

## Identity semantics

Entity `same_entity` and Event `same_occurrence` are the only decisions that union representations.

`uncertain`, `not_same`, and `related_occurrence` do not merge records. `related_occurrence` is published as a relation between distinct CanonicalEvents with provenance back to the originating resolution candidate and staged refs.

Unlinked staged records become singleton canonical records.

Canonical records deliberately contain identity membership rather than copied source presentation data. Entity names, Event titles, Claims, source time, evidence, and provenance remain owned by the staged source layer.

## Existing catalog semantics

Publication accepts an optional existing catalog.

- a known representation reuses its existing canonical UUID;
- a new representation connected by an accepted same-link attaches to the existing UUID;
- a new identity/occurrence receives a new program-generated UUIDv7;
- existing canonical records not touched by the current publication input remain preserved;
- existing `related_occurrence` relations remain preserved;
- if one same-component contains two already-existing canonical UUIDs, publication fails with `PublicationConflict`.

`not_same` and `related_occurrence` act as consistency constraints: if accepted same-links would transitively collapse their endpoints into one canonical record, publication also fails instead of emitting contradictory authority.

## Implementation

Artifacts in this task:

- `apps/chronicle/ingestion/schemas/chronicle-canonical-v0.1.schema.json`;
- `apps/chronicle/ingestion/prototype/publication_v0.py`;
- `apps/chronicle/ingestion/prototype/chronicle_publish.py`;
- `apps/chronicle/ingestion/prototype/test_publication_v0.py`;
- `apps/chronicle/docs/publication.md`.

The publication core uses deterministic ordering and a DSU/union-find grouping algorithm. UUIDv7 generation uses Python standard-library primitives; tests inject an ID factory so identity behavior can be tested deterministically without weakening production UUID semantics.

The CLI accepts repeatable `--bundle LABEL=PATH` and `--resolution PATH` arguments so the publication layer is not limited to the first two-source experiment.

## Verification

The completed C0-T8 implementation passed the full Chronicle prototype discovery:

```text
Ran 61 tests
OK
```

The accepted C0-T7 real Resolution Links used for publication contained:

```text
entities: 5 same_entity + 5 uncertain
events:   8 same_occurrence + 2 related_occurrence
```

The first real 武帝纪 + 吴主传 publication completed with:

```text
chronicle publication: PASS entities=66 events=45 relations=2
```

A full resolution-boundary audit confirmed every `same_entity` / `same_occurrence` pair shared canonical identity and every `uncertain`, `not_same`, and `related_occurrence` pair remained distinct as required.

A rerun using the first catalog as `--existing-catalog` again returned:

```text
chronicle publication: PASS entities=66 events=45 relations=2
PASS: canonical catalog byte-stable
```

The final human-readable semantic inspection confirmed:

- the 武帝纪 and 吴主传 曹操 representations share one CanonicalEntity UUID;
- both 赤壁之战 representations share one CanonicalEvent UUID;
- `曹操进军江陵` and `曹操北还并留军守江陵、襄阳` remain distinct CanonicalEvents under `related_occurrence`;
- all five uncertain same-name place pairs — 襄阳、夏口、江陵、赤壁、合肥 — remain separate canonical identities.

Synthetic CLI verification and the standalone publication test module were also completed before the real-data run.

## Acceptance

- [x] canonical publication JSON Schema exists;
- [x] deterministic publication core exists;
- [x] canonical publication CLI exists;
- [x] program-generated UUIDv7 IDs exist without a new dependency;
- [x] accepted same-links merge representations transitively;
- [x] related/uncertain/not_same decisions do not directly merge records;
- [x] singleton staged records are preserved;
- [x] existing canonical UUIDs are reused;
- [x] conflicting existing canonical IDs fail explicitly;
- [x] offline tests cover identity stability and merge boundaries;
- [x] full Chronicle prototype unittest discovery passes on the implementation branch;
- [x] first real 武帝纪 ↔ 吴主传 publication run is inspected;
- [x] real rerun proves canonical UUID stability;
- [x] delivery PR #475 records the implementation and verification for merge to `main`.

## Boundary to C0-T9

C0-T9 may now persist the accepted canonical catalog. PostgreSQL must store staged data, Resolution Links, and canonical publication as separate auditable layers rather than reinterpreting publication semantics in SQL.
