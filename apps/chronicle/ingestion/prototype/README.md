# Chronicle ingestion prototype

This directory contains the first executable Chronicle ingestion harness.

There are two extractors behind one prototype workflow:

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
Evaluator v2
        ├── hard failures
        └── non-exhaustive gold recall
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

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_cli.py run \
  --extractor rules-v0 \
  --fixture apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13 \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json \
  --output /tmp/chronicle-rules.json \
  --report /tmp/chronicle-rules-report.json
```

For `rules-v0`, schema or exact regression-gold mismatches fail the command.

## Inspect the exact model-v0 prompt

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_cli.py prompt \
  --fixture apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13 \
  --config apps/chronicle/ingestion/config/chronicle-v0.1.yaml \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json \
  > /tmp/chronicle-model-v0-prompt.txt
```

The prompt requires source-only extraction, exact source evidence substrings, no unverified Gregorian month/day conversion, job-local temp IDs, deferred ambiguous entity resolution, `unassessed` Claim assessment, and Event/Claim separation.

The ingestion config also supplies a small controlled Claim predicate vocabulary. Models should emit only canonical values in `claim.predicates.allowed`; aliases exist for evaluator/backward compatibility only.

## Run model-v0 through a command provider

The provider contract is intentionally vendor-neutral:

```text
stdin  = complete Chronicle model-v0 prompt
stdout = one JSON object (plain JSON or one ```json fenced object)
exit   = 0 on provider success
```

Example:

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

The adapter is parsed as argv and executed without `shell=True`. The default timeout is 180 seconds and can be changed with `--model-timeout`.

## Evaluator v2

Model-v0 no longer treats every exact title/predicate difference as an extraction failure.

Evaluator v2 separates:

### Hard failures

These are mechanically provable violations and fail model-v0 execution:

- JSON Schema validation failure;
- Claim evidence is empty or is not an exact substring of SOURCE TEXT;
- Entity has no source-grounded canonical name or mention;
- dangling Entity/Event/Source references;
- fabricated Gregorian month/day from the traditional calendar when the config forbids that conversion;
- Claim predicate outside the configured vocabulary after alias normalization;
- Claim assessment not starting as `unassessed`.

### Semantic evaluation

The committed gold fixture is explicitly **non-exhaustive**. Evaluator v2 therefore reports gold recall plus additional model output instead of pretending that every extra source-grounded item is a false positive.

Event matching does not use title as identity. It scores Event compatibility from:

- Event type;
- normalized/source time fields;
- participant entities;
- participant roles;
- places.

This allows `表卒` and `刘表去世` to represent the same Event when their structured semantics agree.

Claim matching tolerates:

- different temp IDs;
- configured predicate aliases such as `surrendered -> surrendered_to`;
- evidence spans where one exact source substring contains the other;
- selected representation granularity such as an `office` Entity named `丞相` versus the literal value `丞相` for `held_office`.

`--gold-strict` now fails only when required gold content is missing. Additional source-grounded output does not fail merely because the current gold fixture omitted it.

## Re-evaluate an existing staged model result

You do **not** need to call the model again after changing evaluation logic.

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_cli.py evaluate \
  --input /tmp/chronicle-model-v0.json \
  --fixture apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13 \
  --config apps/chronicle/ingestion/config/chronicle-v0.1.yaml \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json \
  --report /tmp/chronicle-model-v0-report-v2.json
```

This is the preferred way to compare Evaluator revisions against the exact same model extraction.

## Replay a captured raw model response

If the provider's raw response was captured, it can also be passed through model normalization again:

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

## Model output normalization

`model-v0` only normalizes transport metadata:

- source/entity/event/claim temp IDs are reassigned deterministically;
- internal references are rewritten;
- `extraction.method` is set to `model`;
- missing Claim assessment defaults to `unassessed`;
- missing Entity resolution defaults to `unresolved`;
- the fixture locator is attached when the model already emitted the relevant metadata/locator object.

It does **not** invent historical facts merely to make the schema pass.

## Validate or use the legacy exact comparison

Schema validation:

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_cli.py validate \
  --input /tmp/chronicle-model-v0.json \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json
```

The old ID-independent exact comparator remains available for debugging only:

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_cli.py compare \
  --model-semantics \
  --input /tmp/chronicle-model-v0.json \
  --expected apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13/expected.yaml
```

It is not the model quality gate anymore.

## Tests

```bash
python3 -m unittest discover \
  -s apps/chronicle/ingestion/prototype \
  -p 'test_*.py' \
  -v
```

The suite covers the deterministic baseline, model prompt/provider/normalization behavior, and Evaluator v2 hard/semantic matching behavior.

## Current limitations

Evaluator v2 is deterministic and intentionally simple. It does not use embeddings or an LLM judge. The Event scorer is a V0 heuristic to be pressure-tested against more fixtures before being generalized.

The predicate vocabulary is likewise intentionally small and must grow from real Chronicle fixtures rather than from an up-front universal ontology design.

Canonical entity resolution, event deduplication, PostgreSQL publishing, verified traditional-calendar month/day conversion, and generalized reusable ingestion remain out of scope.
