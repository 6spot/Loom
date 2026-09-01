---
task: C0-T8
issue: 470
status: in_progress
depends_on: [C0-T7]
created_at: 2026-09-01
started_at: 2026-09-01
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

## Offline verification

A standalone run of the new publication test module currently passes 11 tests:

```text
Ran 11 tests
OK
```

Coverage includes:

- generated UUID version/variant;
- same Entity/Event merge behavior;
- uncertain/related non-merge behavior;
- singleton preservation;
- transitive grouping across three sources;
- reuse/attachment through an existing catalog;
- byte-stable rerun with the first output supplied as the existing catalog;
- conflicting existing canonical IDs;
- transitive `not_same` conflict detection;
- transitive `related_occurrence` conflict detection;
- preservation of existing Event relations;
- input immutability;
- canonical JSON Schema validation;
- mismatched resolution/bundle metadata rejection.

A synthetic CLI publication also completed successfully and a second run with `--existing-catalog` produced byte-identical catalog output.

## First real validation

Before completion, run publication against the final independently ingested 武帝纪 and 吴主传 bundles plus the accepted C0-T7 resolution output.

The run must demonstrate:

- the two 曹操 source representations share one CanonicalEntity UUID;
- the two 赤壁 source Event representations share one CanonicalEvent UUID;
- the Jiangling `related_occurrence` pair remains two CanonicalEvents connected by a relation;
- the five uncertain same-name place links remain separate canonical identities;
- source bundle/Claim content remains unchanged;
- rerun with the first catalog supplied as `--existing-catalog` preserves all canonical UUIDs.

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
- [ ] full Chronicle prototype unittest discovery passes on the implementation branch;
- [ ] first real 武帝纪 ↔ 吴主传 publication run is inspected;
- [ ] real rerun proves canonical UUID stability;
- [ ] delivery PR / merge reconciliation completed.

## Boundary to C0-T9

C0-T9 may persist the canonical catalog only after this task is accepted. PostgreSQL must store staged data, Resolution Links, and canonical publication as separate auditable layers rather than reinterpreting publication semantics in SQL.
