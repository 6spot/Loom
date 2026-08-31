# Chronicle ingestion prototype

This directory contains the first executable Chronicle ingestion harness.

The current model path is:

```text
raw.txt + context.yaml + chronicle-v0.1.yaml
        ↓
model-v0 pass 1
        ↓
immutable staged bundle
        ↓ optional
coverage-v0.2 additions-only review
        ↓
deterministic merge
        ↓
Chronicle v0.1 staged bundle
        ↓
Draft 2020-12 JSON Schema validation
        ↓
Evaluator v2
        ├── hard failures
        └── non-exhaustive gold recall
```

`rules-v0` remains the deterministic fixture-scoped regression baseline. It is not product extraction logic.

`model-v0` is source-grounded and provider-neutral. Its prompt contains only raw source text, document context, ingestion policy, and the Chronicle JSON Schema. `expected.yaml` is loaded only after extraction and never enters the provider input.

`coverage-v0.2` is also closed-book. It receives the same source/context/config/schema plus the exact pass-1 staged bundle. It never receives evaluator output or human-gold data.

## Setup

```bash
python3 -m venv .venv-chronicle
. .venv-chronicle/bin/activate
python3 -m pip install -r apps/chronicle/ingestion/prototype/requirements.txt
```

## Tests

```bash
python3 -m unittest discover \
  -s apps/chronicle/ingestion/prototype \
  -p 'test_*.py' \
  -v
```

The suite covers the deterministic baseline, model prompt/provider/normalization behavior, Evaluator v2, and coverage-v0.2 prompt/merge behavior.

## Deterministic baseline

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_cli.py run \
  --extractor rules-v0 \
  --fixture apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13 \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json \
  --output /tmp/chronicle-rules.json \
  --report /tmp/chronicle-rules-report.json
```

For `rules-v0`, schema or exact regression-gold mismatches fail the command.

## Inspect model-v0 prompt

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_cli.py prompt \
  --fixture apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13 \
  --config apps/chronicle/ingestion/config/chronicle-v0.1.yaml \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json \
  > /tmp/chronicle-model-v0-prompt.txt
```

The model prompt requires source-only extraction, exact evidence substrings, no unverified Gregorian month/day conversion, job-local temp IDs, deferred ambiguous resolution, `unassessed` Claim assessment, and Event/Claim separation.

The ingestion config supplies a small controlled Claim predicate vocabulary. Models should emit canonical values from `claim.predicates.allowed`; aliases exist only for evaluator/backward compatibility.

## Run model-v0 through a command provider

The provider contract is vendor-neutral:

```text
stdin  = complete Chronicle prompt
stdout = one JSON object
exit   = 0 on provider success
```

Example pass-1 run:

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_cli.py run \
  --extractor model-v0 \
  --fixture apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13 \
  --config apps/chronicle/ingestion/config/chronicle-v0.1.yaml \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json \
  --model-command '/path/to/model-adapter --model your-model' \
  --model-timeout 600 \
  --output /tmp/chronicle-model-v0.json \
  --report /tmp/chronicle-model-v0-report.json
```

The command is parsed as argv and executed without `shell=True`.

## Evaluator v2

Evaluator v2 separates mechanically provable failures from semantic differences against the intentionally non-exhaustive human gold fixture.

### Hard failures

These fail model execution/evaluation:

- JSON Schema validation failure;
- Claim evidence missing from SOURCE TEXT;
- Entity with no source-grounded canonical name/mention;
- dangling Entity/Event/Source references;
- fabricated Gregorian month/day from a traditional calendar when forbidden;
- Claim predicate outside the configured vocabulary after alias normalization;
- Claim assessment not starting as `unassessed`.

### Semantic evaluation

Evaluator v2 reports gold recall plus additional output instead of treating every extra source-grounded item as a false positive.

Event matching uses type, time, participants/roles, places, and a weak same-type shared-title-phrase signal. Claim matching tolerates temp-ID differences, configured predicate aliases, evidence-span containment, compatible value/literal surface granularity, and conservative composite coverage. Entity matching is exact by default with limited same-type surface-containment support.

Re-evaluate an existing staged output without another model call:

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_cli.py evaluate \
  --input /tmp/chronicle-model-v0.json \
  --fixture apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13 \
  --config apps/chronicle/ingestion/config/chronicle-v0.1.yaml \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json \
  --report /tmp/chronicle-model-v0-report-v2.json
```

## Coverage v0.2

The first real model run showed that a model may extract relevant entities while still omitting an explicit Event or Claim. Coverage v0.2 performs one second source-grounded audit without adding fixture-specific rules.

### Additions-only protocol

Pass 1 is immutable. The coverage model does **not** return a replacement bundle. It returns only:

```json
{
  "entities": [],
  "events": [],
  "claims": [],
  "warnings": []
}
```

Each array contains only records that are missing from pass 1.

Chronicle then performs a deterministic merge:

- existing pass-1 objects remain byte-for-byte semantically unchanged;
- duplicate Entity records with the same type/name map back to the existing Entity ID;
- new temp IDs are assigned after existing IDs;
- Event/Claim references are rewritten to existing/new IDs;
- obvious duplicate Events/Claims are skipped;
- final full-bundle JSON Schema validation and Evaluator v2 still run afterward.

The report records:

```text
coverage_pass.protocol
coverage_pass.initial_counts
coverage_pass.final_counts
coverage_pass.merge.proposed
coverage_pass.merge.added
coverage_pass.merge.skipped_duplicates
```

This design was adopted after the first full-bundle coverage experiment improved entity/event recall but expanded 13 Events to 29 and reduced Claim recall by rewriting previously-good pass-1 Claims.

### Clean A/B: apply coverage to an existing pass-1 file

This is the preferred experiment because the original model output remains fixed and the only variable is Coverage v0.2:

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_coverage.py \
  --input /tmp/chronicle-model-v0.json \
  --fixture apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13 \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json \
  --config apps/chronicle/ingestion/config/chronicle-v0.1.yaml \
  --model-command '/path/to/model-adapter --model your-model' \
  --model-timeout 600 \
  --output /tmp/chronicle-run2-coverage.json \
  --report /tmp/chronicle-run2-coverage-report.json
```

### Run pass 1 + coverage together

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_cli.py run \
  --extractor model-v0 \
  --coverage-pass \
  --initial-output /tmp/chronicle-model-v0-pass1.json \
  --fixture apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13 \
  --config apps/chronicle/ingestion/config/chronicle-v0.1.yaml \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json \
  --model-command '/path/to/model-adapter --model your-model' \
  --model-timeout 600 \
  --output /tmp/chronicle-model-v0-coverage.json \
  --report /tmp/chronicle-model-v0-coverage-report.json
```

Because this mode invokes the provider for pass 1 again, use the existing-staged runner above for strict A/B measurement.

### Inspect the coverage prompt

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_cli.py coverage-prompt \
  --input /tmp/chronicle-model-v0.json \
  --fixture apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13 \
  --config apps/chronicle/ingestion/config/chronicle-v0.1.yaml \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json \
  > /tmp/chronicle-coverage-v0.2-prompt.txt
```

Coverage remains opt-in while its value is measured.

## Replay a captured raw model response

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

## Validate staged output

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_cli.py validate \
  --input /tmp/chronicle-model-v0.json \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json
```

## Current limitations

Evaluator v2 is deterministic and intentionally simple; it does not use embeddings or an LLM judge. The Event scorer and composite Claim matcher need more fixtures before generalization.

The predicate vocabulary is intentionally small and should grow from real Chronicle fixtures rather than from an up-front universal ontology.

Coverage v0.2 adds one provider call and is opt-in while measured. It is a model audit pass, not a workflow engine.

Canonical entity resolution, final event deduplication/publication semantics, PostgreSQL publishing, verified traditional-calendar month/day conversion, and generalized reusable ingestion remain out of scope.
