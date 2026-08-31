# Chronicle production ingestion path

Chronicle production ingestion is **contract-first**.

```text
raw source + document context + Chronicle contract
                    ↓
             contract-v0 agent
                    ↓
              staged bundle
                    ↓
        deterministic validator
             ↓ pass      ↓ fail
           staged      bounded repair
                         (max 1)
                           ↓
                  deterministic revalidation
```

## Responsibilities

### Contract / schema

Chronicle defines the shape and semantics of `Source`, `Entity`, `Event`, and `Claim`, the controlled predicate vocabulary, evidence requirements, ID policy, and historical-time precision policy.

### Extraction agent

The agent reads the complete source and maps explicit source-grounded historical content into the Chronicle contract. Historical understanding belongs here, not in a second rule/audit engine.

### Validator

The validator checks only mechanically provable violations: JSON Schema, source grounding, reference integrity, predicate vocabulary, initial assessment, forbidden Gregorian precision, and conservative source-calendar consistency when an exact source surface can be located.

A missing optional field is not made mandatory by the validator. If the model declares a source-calendar value and Chronicle can mechanically prove that it conflicts with the text, validation fails.

### Bounded repair

Repair is optional and limited to one pass. It receives the original closed-book inputs, current staged bundle, and deterministic validator errors only. It never receives `expected.yaml`, semantic gold recall, or evaluator mismatch information.

### Evaluator v2

Evaluator v2 is a development/benchmark tool. Human gold is intentionally non-exhaustive and never participates in the production ingestion or repair path.

### Coverage v0.2

Coverage v0.2 is a retained experiment, not a production stage. Its experiments were useful for discovering omission, Event/Claim granularity, pass-2 regression, object-growth, and source-month failure modes. C0-T5 / #466 supersedes it as the production direction.

## Run

```bash
python3 apps/chronicle/ingestion/prototype/chronicle_pipeline.py \
  --fixture apps/chronicle/ingestion/fixtures/sanguozhi-wudi-jianan-13 \
  --schema apps/chronicle/ingestion/schemas/chronicle-v0.1.schema.json \
  --config apps/chronicle/ingestion/config/chronicle-v0.1.yaml \
  --model-command '<model command>' \
  --model-timeout 600 \
  --repair-attempts 1 \
  --output /tmp/chronicle-contract-v0.json \
  --report /tmp/chronicle-contract-v0-report.json
```

Use `chronicle_cli.py evaluate` separately when benchmark/gold metrics are desired.
