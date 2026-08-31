---
task: C0-T5
issue: 466
status: in_progress
depends_on: [C0-T2, C0-T3]
created_at: 2026-08-31
started_at: 2026-08-31
completed_at:
completion_pr:
merge_sha:
---

# Chronicle contract-first ingestion

## Goal

Make Chronicle's production ingestion path simple and model-native: Chronicle defines the staged data contract; the extraction agent reads the source once and maps it into that contract; deterministic code validates only mechanically provable violations; an optional bounded repair pass fixes only those violations.

## Production pipeline

```text
Raw Source + Document Context + Data Contract
                    ↓
             contract-v0 agent
                    ↓
              Staged Bundle
                    ↓
        deterministic validator
             ↓ pass      ↓ fail
           staged     bounded repair (max 1)
                         ↓
                  deterministic revalidation
```

Human gold and Evaluator v2 are development/benchmark tools and are not production inputs.

## Scope

- add a contract-first extraction prompt that asks the model to read the complete source and map explicit historical content to Entity/Event/Claim without a second semantic audit;
- add a deterministic production validator built from JSON Schema and mechanically provable hard checks;
- validate declared traditional source-calendar months only when the relevant source surface can be mechanically located; absence of optional time is not a validator error;
- add an optional one-pass repair prompt driven only by validator errors;
- add a production `chronicle_pipeline.py` entrypoint with no gold/evaluator dependency;
- keep Evaluator v2 available for offline quality measurement;
- retain Coverage v0.2 code/results as an experiment, not as a production pipeline stage;
- no Loom Core/Runtime/Storage changes.

## Non-goals

- using human gold to repair production output;
- a second model coverage/audit stage in production;
- universal historical ontology design;
- canonical entity resolution or PostgreSQL publishing;
- unverified traditional-calendar to Gregorian month/day conversion.

## Acceptance

- [x] `contract_v0.py` defines the single-pass contract-first extraction task.
- [x] `validator_v0.py` produces a gold-free deterministic validation report.
- [x] Validator reuses hard grounding/reference/predicate/time rules and adds conservative source-calendar consistency checks.
- [x] Missing optional source time is not treated as an error solely by the validator.
- [x] `repair_v0.py` receives only current bundle + deterministic validation errors + original closed-book inputs.
- [x] Repair is bounded to at most one attempt in the production CLI.
- [x] `chronicle_pipeline.py` has no `expected.yaml` or semantic evaluator input.
- [x] Offline tests for validator/repair behavior are committed.
- [ ] Full prototype unittest discovery passes in a repository checkout.
- [ ] Real Luna contract-v0 run is executed and compared offline with the earlier model-v0 benchmark.
- [ ] Delivery PR / CI / merge reconciliation completed.

## Decision from Coverage v0.2 experiments

Coverage v0.2 was useful as an experiment because it exposed real failure modes: omitted source actions, Event/Claim granularity problems, pass-2 regressions, object explosion, and traditional source-month mistakes. It also demonstrated that turning coverage into an increasingly detailed semantic audit duplicates the extraction agent's historical-understanding responsibility.

Therefore Coverage v0.2 is not part of the production ingestion architecture. Its code and measurements remain available as research evidence; C0-T5 is the production direction.
