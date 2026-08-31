# Chronicle ingestion prototype

This directory contains the first schema-driven ingestion experiment for Chronicle.

No production ingestion CLI is implemented yet. The files here define the contract and regression fixture that an implementation must satisfy.

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
Chunk extraction
   ↓
Staged Source / Entity / Event / Claim
   ↓
Normalization
   ↓
Schema validation
   ↓
Warnings
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
└── fixtures/
    └── sanguozhi-wudi-jianan-13/
        ├── raw.txt
        ├── context.yaml
        └── expected.yaml
```

## Fixture semantics

`raw.txt` is copied verbatim from the selected source passage.

`context.yaml` supplies document-level context that a future document scan could derive automatically. V0.1 allows this context to be curated so the experiment can focus on extraction behavior.

`expected.yaml` is a curated gold reference. It is not a claim that the current event segmentation is the final historical ontology.

A future evaluator should distinguish:

- **hard checks** — schema validity, evidence preservation, forbidden fake precision, required gold facts;
- **soft checks** — exact event segmentation, optional additional claims, title wording.

LLM output should not be required to match the gold file byte-for-byte.

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
