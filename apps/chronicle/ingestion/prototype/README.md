# Chronicle ingestion prototype

This directory contains the first executable Chronicle ingestion harness.

There are now two extractors behind one prototype workflow:

```text
raw.txt + context.yaml + chronicle-v0.1.yaml
        ↓
┌────────────────────────────┐
│ extractor                  │
│                            │
│ rules-v0  deterministic    │
│ model-v0  model/provider   │
└────────────────────────────┘
        ↓
Chronicle v0.1 staged bundle
        ↓
Draft 2020-12 JSON Schema validation
        ↓
human-gold semantic comparison
        ↓
machine-readable evaluation report
```

`rules-v0` remains deliberately fixture-scoped. It is the deterministic regression baseline, not product extraction logic.

`model-v0` is source-grounded and provider-neutral. It builds its prompt only from the raw source text, document context, ingestion policy, and Chronicle JSON Schema. `expected.yaml` is loaded only **after** model extraction finishes and is never part of the provider input.

## Setup

From the repository root:

```bash
python3 -m venv .venv-chronicle
. .venv-chronicle/bin/activate
python3 -m pip install -r apps/chronicle/ingestion/prototype/requirements.txt
```

## Deterministic baseline

The legacy baseline command is still available:

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_ingest.py run \
  --fixture apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13 \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json \
  --output /tmp/chronicle-staged.json
```

The unified CLI can run the same baseline explicitly:

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_cli.py run \
  --extractor rules-v0 \
  --fixture apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13 \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json \
  --output /tmp/chronicle-rules.json \
  --report /tmp/chronicle-rules-report.json
```

For `rules-v0`, schema or gold mismatches fail the command.

## Inspect the exact model-v0 prompt

Before invoking any provider, the exact closed-book prompt can be rendered:

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_cli.py prompt \
  --fixture apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13 \
  --config apps/chronicle/ingestion/config/chronicle-v0.1.yaml \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json \
  > /tmp/chronicle-model-v0-prompt.txt
```

The prompt explicitly requires:

- extract what the supplied source says, not what the model already knows;
- every Claim evidence string must be an exact source substring;
- traditional months/days must not be converted to Gregorian dates without verified conversion data;
- only job-local temp IDs may be emitted;
- ambiguous entity references must remain unresolved instead of being guessed;
- Claim assessment starts as `unassessed`;
- Event and Claim remain separate layers.

## Run model-v0 through a command provider

The first provider interface is intentionally vendor-neutral:

```text
stdin  = complete Chronicle model-v0 prompt
stdout = one JSON object (plain JSON or one ```json fenced object)
exit   = 0 on provider success
```

Run it with any external adapter/model CLI that follows that contract:

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_cli.py run \
  --extractor model-v0 \
  --fixture apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13 \
  --config apps/chronicle/ingestion/config/chronicle-v0.1.yaml \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json \
  --model-command '/path/to/model-adapter --model your-model' \
  --output /tmp/chronicle-model-v0.json \
  --report /tmp/chronicle-model-v0-report.json
```

The adapter command is parsed as argv and executed without `shell=True`. The default provider timeout is 180 seconds and can be changed with `--model-timeout`.

Model-v0 gold mismatches are reported but do not fail the command by default because the purpose of the first model pass is evaluation. Add `--gold-strict` when exact current gold matching should be a hard gate. JSON Schema failures always fail.

## Replay a captured model response

A model response can be evaluated again without calling a provider:

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_cli.py run \
  --extractor model-v0 \
  --fixture apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13 \
  --config apps/chronicle/ingestion/config/chronicle-v0.1.yaml \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json \
  --model-response /tmp/raw-model-response.txt \
  --output /tmp/chronicle-model-v0.json \
  --report /tmp/chronicle-model-v0-report.json
```

This makes model experiments reproducible without putting API credentials or a permanent vendor dependency into Chronicle.

## Model output normalization

`model-v0` only normalizes transport metadata:

- source/entity/event/claim temp IDs are reassigned deterministically;
- internal references are rewritten to the new temp IDs;
- `extraction.method` is set to `model`;
- missing Claim assessment defaults to `unassessed`;
- missing Entity resolution defaults to `unresolved`;
- the fixture locator is attached when the model already emitted the relevant metadata/locator object.

It does **not** fill missing historical facts merely to make the schema pass. Historical content remains the model's extraction result and must survive JSON Schema validation.

Gold evaluation dereferences temp IDs to entity names/event titles before comparing, so a model is not penalized merely for choosing a different temp-ID spelling or ordering.

## Validate or compare an existing staged bundle

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_cli.py validate \
  --input /tmp/chronicle-model-v0.json \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json
```

For model-style ID-independent comparison:

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_cli.py compare \
  --model-semantics \
  --input /tmp/chronicle-model-v0.json \
  --expected apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13/expected.yaml
```

## Tests

```bash
python3 -m unittest discover \
  -s apps/chronicle/ingestion/prototype \
  -p 'test_*.py' \
  -v
```

The original four rules-v0 tests remain. Model-v0 adds coverage for prompt isolation, command-provider invocation, plain/fenced JSON parsing, transport-ID normalization, ID-independent comparison, and evaluation reporting.

The complete committed fixture remains the regression baseline for the 15-entity / 12-event / 9-claim vertical slice.

## Current limitations

The model provider contract is intentionally small and vendor-neutral. Chronicle does not yet choose a permanent model vendor or implement production API-key management.

Canonical entity resolution, event deduplication, PostgreSQL publishing, verified traditional-calendar month/day conversion, and generalized reusable ingestion remain out of scope.
