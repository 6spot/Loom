# Chronicle production ingestion path

Chronicle production ingestion is **contract-first**.

```text
raw source + document context + Chronicle contract
                    ↓
            contract-v0.2 agent
                    ↓
              staged bundle
                    ↓
        deterministic validator
             ↓ pass      ↓ fail
           staged      bounded patch repair
                         (max 1)
                           ↓
                  deterministic revalidation
                    ↓ pass      ↓ fail
                  staged      no output
```

## Responsibilities

### Contract / schema

Chronicle defines the shape and semantics of `Source`, `Entity`, `Event`, and `Claim`, the controlled predicate vocabulary, evidence requirements, ID policy, Event-boundary policy, and historical-time precision policy.

Contract v0.2 makes four production expectations explicit:

- distinct independent actions should normally become separate timeline Events rather than one compound Event;
- an allowed Claim predicate must faithfully represent the source assertion; a merely related predicate must not be used as fallback;
- if the current predicate vocabulary cannot faithfully express an assertion, retain the source-grounded Event/Entity representation where appropriate and emit an `ontology_gap` warning instead of inventing or misusing a predicate;
- Events must retain explicit or safely inherited traditional/regnal source time when available, while normalized Gregorian month/day remain null unless verified conversion exists.

### Extraction agent

The agent reads the complete source and maps explicit source-grounded historical content into the Chronicle contract. Historical understanding belongs here, not in a second rule/audit engine.

### Validator

The validator checks only mechanically provable violations: JSON Schema, source grounding, reference integrity, predicate vocabulary, initial assessment, forbidden Gregorian precision, and conservative source-calendar consistency when an exact source surface can be located.

A missing optional field is not made mandatory by the validator. If the model declares a source-calendar value and Chronicle can mechanically prove that it conflicts with the text, validation fails.

### Bounded repair

Repair is optional and limited to one pass. It receives the original closed-book inputs, current staged bundle, and deterministic validator errors only. It never receives `expected.yaml`, semantic gold recall, or evaluator mismatch information.

Repair-v0.2 is **patch-only**. The model cannot return or replace the whole bundle. It may only:

- replace a specifically named existing Source/Entity/Event/Claim record while preserving its identity;
- add a genuinely missing source-grounded record required by a listed validation error;
- remove an exact stale warning message and optionally add a corrected warning.

Unmentioned historical records are immutable. Existing Source/Entity/Event/Claim records cannot be deleted by repair.

The deterministic program applies the patch and validates the resulting candidate. A repair candidate is accepted only if revalidation passes. `--output` is written only for a passing bundle; a failed repair candidate can be inspected separately with `--repair-candidate-output` and can never overwrite staged output.

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
  --initial-output /tmp/chronicle-contract-v0.2-initial.json \
  --raw-repair-response /tmp/chronicle-contract-v0.2-repair-patch.json \
  --repair-candidate-output /tmp/chronicle-contract-v0.2-repair-candidate.json \
  --output /tmp/chronicle-contract-v0.2.json \
  --report /tmp/chronicle-contract-v0.2-report.json
```

`--initial-output` preserves the normalized pre-repair bundle. `--raw-repair-response` preserves the model patch. `--repair-candidate-output` preserves the deterministic patched candidate even when revalidation fails.

Use `chronicle_cli.py evaluate` separately when benchmark/gold metrics are desired.
