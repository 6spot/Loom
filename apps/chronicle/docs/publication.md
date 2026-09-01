# Chronicle canonical publication v0.1

Canonical publication is Chronicle's deterministic identity layer above source-owned staged bundles and cross-source Resolution Links.

```text
source-owned staged bundles
        +
resolution links
        +
optional existing canonical catalog
        ↓
canonical publication
        ↓
CanonicalEntity / CanonicalEvent identity membership
        +
canonical Event relations
```

Publication does not call a model and does not use human gold.

## Authority boundary

The staged bundle remains the authority for source-specific data such as:

- Entity names, aliases, mentions, descriptions, and attributes;
- Event titles, summaries, source time, participants, and places;
- Claims, evidence, provenance, and assessment;
- Source metadata.

The canonical catalog owns only cross-source identity membership and canonical Event-to-Event relations. It deliberately does not copy a preferred Entity name or Event title into canonical identity, because names and titles are presentation surfaces rather than identity authority.

Resolution Links remain a separate derived layer. Publication consumes accepted link decisions but does not rewrite their rationale, confidence, signals, or source refs.

## Merge semantics

Only these decisions may union staged representations:

- Entity `same_entity`;
- Event `same_occurrence`.

These decisions never cause union:

- Entity/Event `uncertain`;
- Entity/Event `not_same`;
- Event `related_occurrence`.

`related_occurrence` becomes a relation between two distinct CanonicalEvents. The relation preserves the originating resolution candidate and staged left/right refs so it can be traced back to the Resolution Link layer.

`not_same` and `related_occurrence` are also enforced as negative consistency constraints. If other accepted same-links would transitively place their two endpoints under one canonical ID, publication fails with `PublicationConflict` instead of emitting a self-contradictory catalog. `uncertain` remains non-merging evidence but is not treated as a hard negative constraint.

Unlinked staged Entity/Event records publish as singleton canonical records.

## Canonical IDs

Canonical IDs are program-generated UUIDv7 values. The v0 implementation uses only Python standard-library primitives and follows the RFC 9562 UUIDv7 bit layout.

First publication of a new identity creates a UUIDv7. Later publication with `--existing-catalog` reuses the existing UUID whenever a staged representation is already a member of that canonical record.

If a new accepted same-link connects a new representation to an existing canonical record, the representation attaches to the existing UUID.

If publication would require collapsing two already-existing canonical UUIDs into one, it fails with `PublicationConflict`. Publication never chooses one existing ID silently and never generates a replacement ID for the conflict.

Existing canonical records and existing `related_occurrence` relations are preserved when an existing catalog is supplied.

## Multi-source behavior

Publication accepts repeated staged bundles and repeated pairwise Resolution Link files. Same-links are closed transitively across the supplied graph, so for example:

```text
source A representation
    same_entity
source B representation
    same_entity
source C representation
```

publishes as one CanonicalEntity.

Resolution files must refer to supplied bundle labels and their `source_ref` / `source_title` metadata must match the supplied staged bundle. This prevents a resolution artifact from being applied to the wrong source bundle by label alone.

## Catalog contract

The machine-readable contract is:

```text
apps/chronicle/ingestion/schemas/chronicle-canonical-v0.1.schema.json
```

The top-level catalog contains:

```json
{
  "schema": "chronicle.canonical-catalog",
  "version": "0.1",
  "canonical_entities": [],
  "canonical_events": [],
  "event_relations": [],
  "warnings": []
}
```

Each canonical Entity/Event contains only:

- `canonical_id`;
- `representations[]` as `{bundle, ref}` membership.

Each canonical Event relation contains:

- `type: related_occurrence`;
- two distinct canonical Event UUIDs;
- `resolution_links[]` provenance back to candidate ID and staged refs.

Publication emits no timestamp into the catalog so a rerun against an unchanged existing catalog can remain byte-stable after deterministic ordering.

## CLI

The publication CLI is:

```text
apps/chronicle/ingestion/prototype/chronicle_publish.py
```

Example for the first two Chronicle sources:

```bash
ART=apps/chronicle/.artifacts/c0-t7

python3 apps/chronicle/ingestion/prototype/chronicle_publish.py \
  --bundle wudi="$ART/wudi/final.json" \
  --bundle wuzhu="$ART/wuzhu/final.json" \
  --resolution "$ART/resolution/final.json" \
  --schema apps/chronicle/ingestion/schemas/chronicle-canonical-v0.1.schema.json \
  --output "$ART/publication/catalog.json" \
  --report "$ART/publication/report.json"
```

Identity-stability rerun:

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_publish.py \
  --bundle wudi="$ART/wudi/final.json" \
  --bundle wuzhu="$ART/wuzhu/final.json" \
  --resolution "$ART/resolution/final.json" \
  --existing-catalog "$ART/publication/catalog.json" \
  --schema apps/chronicle/ingestion/schemas/chronicle-canonical-v0.1.schema.json \
  --output "$ART/publication/catalog-rerun.json" \
  --report "$ART/publication/report-rerun.json"

cmp "$ART/publication/catalog.json" "$ART/publication/catalog-rerun.json"
```

The report records canonical counts, representation counts, relation count, and new/reused canonical IDs. It is run metadata rather than canonical identity authority.

## Verification

Offline publication tests cover:

- UUIDv7 generation;
- same-link merge boundaries;
- singleton preservation;
- transitive multi-source grouping;
- existing UUID reuse;
- byte-stable rerun with an existing catalog;
- conflicting existing canonical IDs;
- `not_same` / `related_occurrence` consistency conflicts;
- existing relation preservation;
- staged/resolution input immutability;
- canonical JSON Schema validation;
- bundle/resolution metadata mismatch rejection.

The first real acceptance run uses the independently ingested 武帝纪 and 吴主传 bundles plus the accepted C0-T7 Resolution Links. It must show one canonical 曹操 identity, one canonical 赤壁 occurrence, distinct but related Jiangling Events, and no automatic merge of the five uncertain same-name place pairs.
