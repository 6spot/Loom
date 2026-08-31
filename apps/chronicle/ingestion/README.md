# Chronicle ingestion prototype

This directory contains the first schema-driven ingestion experiment for Chronicle.

An executable **prototype harness** lives under [`prototype/`](prototype/). It is intentionally not yet a production/general historical ingestion CLI. The files here define the stable contract and regression fixture that extractors must satisfy.

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
Document context + ingestion policy
   ↓
Extractor
   ├── rules-v0  deterministic regression baseline
   └── model-v0  source-grounded provider path
   ↓
Staged Source / Entity / Event / Claim
   ↓
Transport normalization
   ↓
Schema validation
   ↓
Human-gold comparison + evaluation report + warnings
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
    ├── chronicle_cli.py
    ├── model_v0.py
    ├── test_chronicle_ingest.py
    ├── test_model_v0.py
    ├── requirements.txt
    └── README.md
```

See [`prototype/README.md`](prototype/README.md) for setup, baseline execution, model-v0 provider contract, prompt inspection, replay, schema validation, gold comparison, evaluation reporting, and tests.

## Fixture semantics

`raw.txt` is copied verbatim from the selected source passage.

`context.yaml` supplies document-level context that a future document scan could derive automatically. V0.1 allows this context to be curated so the experiment can focus on extraction behavior.

`expected.yaml` is a curated gold reference. It is not a claim that the current event segmentation is the final historical ontology.

For `model-v0`, `expected.yaml` is intentionally outside the extraction input path. It is loaded only after the provider has returned a staged result.

Evaluation distinguishes:

- **hard checks** — schema validity, evidence preservation, forbidden fake precision, required structure;
- **semantic comparison** — source/entity/event/claim structures after extractor-only diagnostics and temporary-ID spelling are removed;
- **warnings** — uncertainty and intentional limitations remain visible but do not masquerade as historical facts.

## Current executable extractors

### rules-v0

`rules-v0` is a deterministic extractor for the committed Jian'an 13 fixture. Its purpose is to prove the downstream harness without pretending that hand-written phrase rules are the eventual ingestion solution.

For the committed fixture it is expected to produce:

- 15 entities;
- 12 events;
- 9 claims;
- traditional month expressions preserved in `source_calendar`;
- only the safe 建安十三年 → 208 year normalization in `normalized`.

### model-v0

`model-v0` is the first model/config-driven path. It receives only:

- `raw.txt`;
- `context.yaml`;
- `chronicle-v0.1.yaml`;
- `chronicle-v0.1.schema.json`;
- fixed source-grounded extraction instructions.

Its prompt explicitly requires the model to extract what the source says rather than what it already knows. Claim evidence must be copied from the source, ambiguous resolution must remain unresolved, and unsupported calendar precision must not be invented.

The first provider adapter is command-based and vendor-neutral: prompt on stdin, model response on stdout. A replay provider supports deterministic re-evaluation of captured model responses. Choosing a permanent model vendor and production credential handling are intentionally deferred.

## Current acceptance target

The current prototype is successful when it can:

- keep the deterministic rules-v0 regression fixture passing;
- invoke model-v0 without giving the model the human-gold output;
- produce one staged bundle;
- validate the bundle against `chronicle-v0.1.schema.json`;
- preserve evidence for every Claim;
- preserve historical time precision without fake Gregorian month/day conversion;
- report ambiguity instead of guessing;
- produce a useful machine-readable report describing object counts, schema errors, and gold mismatches.

Database writes, UI, PDF/OCR, web crawling, and large-corpus processing remain out of scope for this slice.

## What should be generalized later

Only after several Chronicle fixtures work should we decide whether these mechanisms belong in a reusable Loom capability:

- schema-driven extraction;
- configurable normalizers;
- configurable resolvers;
- validation;
- staged/published lifecycle.

The Chronicle contract should prove the need before a generic ingestion platform is created.
