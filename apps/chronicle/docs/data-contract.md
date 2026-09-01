# Chronicle Data Contract v0.1

Status: **prototype contract for the first ingestion vertical slice**

This document defines the minimum application-level historical data contract used to validate Chronicle ingestion before the UI or corpus grows.

Chronicle `Entity`, `Event`, `Claim`, and `Source` records in this document are **application-domain ingestion records**. They do not introduce new Loom Core primitives, persistence authority, or Runtime semantics.

## Goal

The first validation target is deliberately narrow:

```text
raw historical text
        ↓
document context
        ↓
structured extraction
        ↓
normalization
        ↓
schema validation
        ↓
staged Chronicle bundle
        ↓
later resolution / publication
```

The contract must be strong enough to support the first Chronicle surfaces:

- Timeline
- Event detail
- Entity / person detail
- Sources
- Why / claim exploration
- Historical-moment browsing

It is not intended to be a final world-history ontology.

## Top-level record kinds

V0.1 has four top-level record kinds:

1. `Source`
2. `Entity`
3. `Event`
4. `Claim`

Everything else is a nested structure or a later derived view.

## Identity

Names, romanization, titles, dates, and slugs must never be database identity.

### Staged identity

Extraction produces job-local temporary IDs:

```text
src_001
ent_001
evt_001
clm_001
```

Temporary IDs exist only so records inside one ingestion bundle can reference each other before entity/event resolution.

### Published identity

Published canonical records use UUIDv7.

```text
019...
```

The exact display name or URL slug may change without changing identity.

### Invariant

An ingestion record has either:

- `temp_id` while staged; or
- canonical `id` after publication;

but never both.

The extraction model must not invent canonical UUIDs. Canonical IDs are assigned by the publication/resolution layer.

## Source

A Source describes the material from which claims and events are extracted.

Example:

```json
{
  "temp_id": "src_001",
  "kind": "source",
  "source_type": "book",
  "title": "三国志·魏书·武帝纪",
  "author": "陈寿",
  "language": "lzh"
}
```

A Source identifies the work or source object. Exact evidence location is attached to each Claim through `evidence.locator`.

## Entity

Entity is a persistent historical identity candidate.

V0.1 entity types:

```text
person
place
polity
organization
army
office
group
other
```

Example staged entity:

```json
{
  "temp_id": "ent_001",
  "kind": "entity",
  "type": "person",
  "canonical_name": "曹操",
  "aliases": [],
  "mentions": [
    {
      "text": "公",
      "contextual": true
    }
  ],
  "resolution": {
    "status": "unresolved"
  }
}
```

`canonical_name` is the preferred label for this staged candidate, not identity.

`mentions` preserve how the entity actually appeared in the source. Contextual mentions such as `公`, `表`, `备`, and `权` must be distinguishable from stable names.

Entity resolution is deliberately deferred:

```text
mention
  ↓
staged entity candidate
  ↓
resolver
  ├─ existing canonical UUID
  ├─ create new canonical UUID
  └─ ambiguous / unresolved
```

## Event

Event is Chronicle's primary historical browsing unit.

V0.1 event types include:

```text
political
administrative
military
battle
movement
death
birth
succession
appointment
surrender
diplomatic
epidemic
territorial_change
economic
cultural
other
```

Event boundaries are intentionally revisable. Multiple source claims may later resolve into one canonical event, or one coarse event may later be split into children.

Example:

```json
{
  "temp_id": "evt_003",
  "kind": "event",
  "type": "death",
  "title": "刘表去世",
  "time": {
    "original_text": "八月",
    "source_calendar": {
      "system": "chinese_lunisolar_regnal",
      "era": "建安",
      "era_year": 13,
      "season": "autumn",
      "month": 8
    },
    "normalized": {
      "calendar": "proleptic_gregorian",
      "year": 208,
      "month": null,
      "day": null,
      "precision": "year",
      "conversion_status": "year_only"
    }
  }
}
```

## Historical time

Historical time must preserve the source expression even when normalization is incomplete.

The contract separates:

- `original_text` — exactly the expression used by the source or inherited local phrase;
- `source_calendar` — parsed source-calendar fields;
- `normalized` — only what can be safely converted.

For the first fixture:

```text
建安十三年 -> 208
```

is allowed.

But:

```text
建安十三年七月 -> 208-07
```

is **not** allowed unless a calendar converter has actually mapped the traditional lunisolar month into the target calendar.

Therefore the first fixture keeps the source month while normalizing only the year:

```json
{
  "source_calendar": {
    "era": "建安",
    "era_year": 13,
    "month": 7
  },
  "normalized": {
    "year": 208,
    "month": null,
    "day": null,
    "precision": "year",
    "conversion_status": "year_only"
  }
}
```

Unknown or partially inherited time is valid. The system must prefer `unknown` / partial data over fabricated precision.

`inherited_fields` records which calendar fields were recovered from document context instead of being repeated in the local phrase.

## Claim

Claim is the provenance-bearing knowledge unit.

An Event is a browsing object. A Claim records what a source actually supports.

Example:

```json
{
  "temp_id": "clm_002",
  "kind": "claim",
  "subject": {
    "kind": "entity_ref",
    "ref": "ent_002"
  },
  "predicate": "died",
  "object": null,
  "evidence": {
    "text": "八月，表卒",
    "source_ref": "src_001"
  },
  "assessment": {
    "status": "unassessed"
  }
}
```

A second source that disagrees must create another Claim. It must not overwrite the first source record.

## Evidence

Every Claim requires evidence containing:

- verbatim source text;
- source reference;
- a source locator.

Evidence is not optional in V0.1.

This makes the staged output auditable and lets later Chronicle views expose source provenance.

## Extraction confidence vs historical assessment

These are separate concepts and must never share one `confidence` field.

### Extraction

`extraction.confidence` means:

> How confident is the parser/model that it extracted the source correctly?

It does **not** mean the historical proposition is true.

### Assessment

`assessment.status` describes later corpus-level evaluation:

```text
unassessed
supported
disputed
uncertain
rejected
```

Initial ingestion should normally produce `unassessed`.

Historical assessment belongs after source comparison and resolution, not inside first-pass extraction.

## Raw, staged, published

Chronicle keeps the three states separate.

### Raw

Unmodified source material.

### Staged

Structured extraction using `temp_id`, unresolved identities, source evidence, and warnings.

### Published

Validated records after resolution/deduplication have canonical UUIDv7 identities and are ready to enter the Chronicle corpus.

A schema or resolver upgrade must be able to replay from Raw rather than treating staged JSON as the only surviving source.

## Warnings

A successful bundle may still contain warnings.

Warnings are first-class output for cases such as:

- contextual coreference;
- unresolved or ambiguous entity identity;
- partial historical-calendar conversion;
- uncertain event boundaries;
- missing source metadata.

The goal is not to force the model to decide everything. The goal is to automate certain work and expose uncertainty explicitly.

## V0.1 invariants

1. Names and transliterations are never canonical identity.
2. LLM extraction never assigns canonical UUIDs.
3. Every Claim has verbatim evidence and a Source reference.
4. Original historical time expressions are preserved.
5. Calendar normalization never invents precision.
6. Extraction confidence is separate from historical assessment.
7. Entity resolution and event deduplication are separate from extraction.
8. Source disagreement creates multiple claims rather than destructive merging.
9. Raw input remains replayable.
10. The contract remains an application-level Chronicle prototype until repeated use proves a reusable Loom capability boundary.

## Machine-readable schema

The prototype JSON Schema lives at:

```text
apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json
```

The first curated fixture lives at:

```text
apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13/
```
