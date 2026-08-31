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
- [x] Real Luna contract-v0 run executed successfully with deterministic bounded repair.
- [x] Final contract-v0 output measured offline with Evaluator v2 without feeding evaluator/gold back into production.
- [ ] Delivery PR / CI / merge reconciliation completed.

## Real Luna verification

A real `gpt-5.6-luna` run through the production `chronicle_pipeline.py` completed with:

```text
initial validator errors = 4
repair attempts = 1
final validator errors = 0
result = PASS
```

The four initial errors were all mechanically provable and therefore appropriate repair inputs:

- Event 17 missing required `type`;
- Event 17 had invalid `kind` instead of `event`;
- Event 19 used invalid Event type `retreat` rather than the controlled Event type vocabulary;
- one Event referenced `夏口` as a place without an Entity reference.

The one bounded repair pass corrected those violations. Final production counts were 29 Entities / 23 Events / 29 Claims / 3 warnings, with zero schema, grounding, reference-integrity, time-precision, predicate-vocabulary, assessment, or source-calendar-consistency violations.

Offline Evaluator v2 measurement of the final staged bundle, performed only after production finished, reported:

- Entity gold recall: 13/15 (0.867);
- Event gold recall: 12/12 (1.0);
- Claim gold recall: 9/9 (1.0);
- hard failures: 0.

The evaluator result is a development quality signal, not a production acceptance criterion. The gold fixture is intentionally non-exhaustive, so 100% Event/Claim recall does not imply semantic perfection or precision.

## Remaining quality observations

Inspection of the real final bundle shows the next work belongs in the Contract/schema semantics rather than a second extraction system:

- a stale warning still states that `夏口` was not materialized as an Entity even though the repaired final bundle contains a `夏口` Entity and uses it in the Event; this is a mechanically detectable internal-consistency issue;
- several valid-schema predicates are semantically coarse for the exact source wording, so controlled predicate guidance may need to become clearer without expanding into a universal ontology;
- some Event boundaries remain broader than the preferred atomic policy (for example a combined movement/relief sequence), which should be addressed through extraction-contract guidance rather than deterministic historical inference;
- `江南诸郡` vs normalized broader `江南`, and `江夏太守` vs jurisdictional `江夏`, remain resolution/granularity questions rather than extraction hard failures.

## Decision from Coverage v0.2 experiments

Coverage v0.2 was useful as an experiment because it exposed real failure modes: omitted source actions, Event/Claim granularity problems, pass-2 regressions, object explosion, and traditional source-month mistakes. It also demonstrated that turning coverage into an increasingly detailed semantic audit duplicates the extraction agent's historical-understanding responsibility.

Therefore Coverage v0.2 is not part of the production ingestion architecture. Its code and measurements remain available as research evidence; C0-T5 is the production direction.
