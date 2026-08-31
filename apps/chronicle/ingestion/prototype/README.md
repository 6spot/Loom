# Chronicle ingestion prototype

This directory contains the first executable Chronicle ingestion harness.

It is intentionally **not** a general historical parser. `rules-v0` is a deterministic, fixture-scoped extractor used to prove the stable pipeline around extraction:

```text
raw.txt + context.yaml
        ↓
rules-v0 extractor
        ↓
Chronicle v0.1 staged bundle
        ↓
Draft 2020-12 JSON Schema validation
        ↓
human-gold semantic comparison
```

A future LLM-backed extractor should replace `RulesV0Extractor` while preserving the staged v0.1 contract, validator, warnings, and gold-comparison harness.

## Setup

From the repository root:

```bash
python3 -m venv .venv-chronicle
. .venv-chronicle/bin/activate
python3 -m pip install -r apps/chronicle/ingestion/prototype/requirements.txt
```

## Run the committed fixture

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_ingest.py run \
  --fixture apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13 \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json \
  --output /tmp/chronicle-staged.json
```

The command exits non-zero when either JSON Schema validation or semantic comparison with `expected.yaml` fails.

The emitted JSON contains extractor diagnostics under `extraction` and `warnings`. Gold comparison intentionally ignores those fields and compares the stable source/entity/event/claim semantics.

## Validate an existing staged bundle

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_ingest.py validate \
  --input /tmp/chronicle-staged.json \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json
```

## Compare with human gold

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_ingest.py compare \
  --input /tmp/chronicle-staged.json \
  --expected apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13/expected.yaml
```

## Tests

```bash
python3 -m unittest discover \
  -s apps/chronicle/ingestion/prototype \
  -p 'test_*.py' \
  -v
```

The unit tests are deliberately smaller than the committed fixture. The complete fixture is the regression test for the full 15-entity / 12-event / 9-claim vertical slice.

## Current limitation

The phrase/entity rules in `chronicle_ingest.py` are test scaffolding, not product logic. Do not grow them into a giant historical rule table. The next extraction implementation should be model/config driven and should emit the same staged contract, including explicit warnings when resolution is uncertain.
