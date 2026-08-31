# Chronicle ingestion prototype

This directory contains the first schema-driven ingestion experiment for Chronicle.

An executable **prototype harness** now lives under [`prototype/`](prototype/). It is deliberately fixture-scoped and is not a production/general historical ingestion CLI. The files here define the stable contract and regression fixture that future extractors must satisfy.

## First question to validate

The prototype is not testing whether an LLM can produce arbitrary JSON.

It is testing whether a real historical passage can be transformed into Chronicle data while preserving:

1. document context;
2. contextual entity mentions;
3. historical time precision;
4. event boundaries;
5. Claim / Event separation;
6. source evidence;
7. explicit uncertainty.

## Pipeline

```text
Raw document
   ↓
Document context
   ↓
Extractor
   ↓
Staged Source / Entity / Event / Claim
   ↓
Normalization
   ↓
Schema validation
   ↓
Human-gold comparison + warnings
   ↓
later: entity resolution / event resolution / publication
```

Entity resolution and event deduplication are intentionally **not** part of the first extraction pass.

## Layout

```text
ingestion/
├── config/
│   └── chronicle-v0.1.yaml
├── schemas/
│   └── chronicle-v0.1.schema.json
├── fixtures/
│   └── sanguozhi-wudi-jianan-13/
│       ├── raw.txt
│       ├── context.yaml
│       └── expected.yaml
└── prototype/
    ├── chronicle_ingest.py
    ├── test_chronicle_ingest.py
    ├── requirements.txt
    └── README.md
```

See [`prototype/README.md`](prototype/README.md) for setup, fixture execution, standalone schema validation, gold comparison, and tests.

## Fixture semantics

`raw.txt` is copied verbatim from the selected source passage.

`context.yaml` supplies document-level context that a future document scan could derive automatically. V0.1 allows this context to be curated so the experiment can focus on extraction behavior.

`expected.yaml` is a curated gold reference. It is not a claim that the current event segmentation is the final historical ontology.

Evaluation distinguishes:

- **hard checks** — schema validity, evidence preservation, forbidden fake precision, required gold facts;
- **semantic comparison** — source/entity/event/claim structures after extractor-only diagnostics are removed;
- **warnings** — uncertainty and intentional limitations remain visible but do not masquerade as historical facts.

## Current executable baseline

`rules-v0` is a deterministic extractor for the committed Jian'an 13 fixture. Its purpose is to prove the downstream harness without pretending that hand-written phrase rules are the eventual ingestion solution.

For the committed fixture it is expected to produce:

- 15 entities;
- 12 events;
- 9 claims;
- traditional month expressions preserved in `source_calendar`;
- only the safe 建安十三年 → 208 year normalization in `normalized`.

A future model/config-driven extractor should replace `rules-v0` while keeping the staged v0.1 contract and regression harness stable.

## First implementation acceptance target

A minimal implementation is successful when it can:

- read `raw.txt` and `context.yaml`;
- produce one staged bundle;
- validate the bundle against `chronicle-v0.1.schema.json`;
- preserve evidence for every Claim;
- resolve contextual mentions such as `公`, `表`, `琮`, `备`, and `权` only through available document context;
- normalize 建安十三年 to year 208 without pretending traditional months are Gregorian months;
- emit warnings rather than inventing values when resolution is uncertain.

Database writes, UI, PDF/OCR, web crawling, and large-corpus processing are out of scope for this first slice.

## What should be generalized later

Only after several Chronicle fixtures work should we decide whether these mechanisms belong in a reusable Loom capability:

- schema-driven extraction;
- configurable normalizers;
- configurable resolvers;
- validation;
- staged/published lifecycle.

The Chronicle contract should prove the need before a generic ingestion platform is created.
