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
           contract-v0.2 agent
                    ↓
              Staged Bundle
                    ↓
        deterministic validator
             ↓ pass      ↓ fail
           staged     bounded patch repair (max 1)
                         ↓
                  deterministic revalidation
                    ↓ pass      ↓ fail
                  staged      no output
```

Human gold and Evaluator v2 are development/benchmark tools and are not production inputs.

## Scope

- use one contract-first extraction pass with no production coverage/audit stage;
- add a deterministic production validator built from JSON Schema and mechanically provable hard checks;
- validate declared traditional source-calendar months only when the relevant source surface can be mechanically located; absence of optional time is not a validator error;
- add an optional one-pass repair driven only by validator errors;
- keep Evaluator v2 available only for offline quality measurement;
- retain Coverage v0.2 code/results as an experiment, not as a production pipeline stage;
- refine Contract v0.2 from the first real production run: preserve explicit/inherited source time on Events, split distinct independent actions, forbid semantically-near predicate fallback, expose ontology gaps, and keep post-repair warnings consistent with the final bundle;
- persist pre-repair staged output for repair auditing;
- make repair patch-only so unrelated staged records cannot be rewritten or deleted;
- accept a repair candidate only after deterministic revalidation and write staged output only on PASS;
- no Loom Core/Runtime/Storage changes.

## Non-goals

- using human gold to repair production output;
- a second model coverage/audit stage in production;
- universal historical ontology design;
- canonical entity resolution or PostgreSQL publishing;
- unverified traditional-calendar to Gregorian month/day conversion.

## Acceptance

- [x] `contract_v0.py` defines the single-pass contract-first extraction task.
- [x] Contract v0.2 requires explicit/safely-inherited traditional Event time while preserving year-only Gregorian normalization.
- [x] Contract v0.2 tells the agent to split independent timeline actions and avoid over-combining Event boundaries.
- [x] Contract v0.2 forbids semantically-near predicate fallback and uses `ontology_gap` warnings when the controlled vocabulary cannot faithfully express an assertion.
- [x] `validator_v0.py` produces a gold-free deterministic validation report.
- [x] Validator reuses hard grounding/reference/predicate/time rules and adds conservative source-calendar consistency checks.
- [x] Missing optional source time is not treated as an error solely by the validator.
- [x] `repair_v0.py` receives only current bundle + deterministic validation errors + original closed-book inputs.
- [x] Repair is bounded to at most one attempt.
- [x] Repair-v0.2 is patch-only: unmentioned historical records are immutable and existing Source/Entity/Event/Claim records cannot be deleted.
- [x] Repair patch supports targeted replacement, source-grounded additions required by validation, and exact stale-warning removal.
- [x] Repair candidate is accepted only after deterministic revalidation.
- [x] Failed repair candidates cannot overwrite `--output`; candidate inspection is opt-in via `--repair-candidate-output`.
- [x] `chronicle_pipeline.py` has no `expected.yaml` or semantic evaluator input.
- [x] `chronicle_pipeline.py --initial-output` persists normalized pre-repair output for direct auditing.
- [x] Offline tests for contract/validator/patch-repair behavior are committed.
- [ ] Full prototype unittest discovery passes in a repository checkout after patch-repair revision.
- [x] Real Luna contract-v0 run executed successfully with deterministic bounded repair.
- [x] Final contract-v0 output measured offline with Evaluator v2 without feeding evaluator/gold back into production.
- [x] First real Luna contract-v0.2 run exposed full-bundle repair collapse and was rejected as unsafe.
- [ ] Real Luna contract-v0.2 patch-repair run verifies time retention, predicate fidelity, Event boundaries, warning consistency, and repair preservation.
- [ ] Delivery PR / CI / merge reconciliation completed.

## Real Luna verification — Contract v0

A real `gpt-5.6-luna` run through the production `chronicle_pipeline.py` completed with:

```text
initial validator errors = 4
repair attempts = 1
final validator errors = 0
result = PASS
```

The four initial errors were all mechanically provable and therefore appropriate repair inputs:

- one Event object was missing required `type` and had invalid Event `kind`;
- one Event used invalid Event type `retreat` rather than the controlled Event vocabulary;
- one Event referenced `夏口` as a place without a corresponding Entity.

The one bounded repair pass corrected those violations. Final production counts were 29 Entities / 23 Events / 29 Claims / 3 warnings, with zero schema, grounding, reference-integrity, time-precision, predicate-vocabulary, assessment, or source-calendar-consistency violations.

Offline Evaluator v2 measurement of the final staged bundle, performed only after production finished, reported:

- Entity gold recall: 13/15 (0.867);
- Event gold recall: 12/12 (1.0);
- Claim gold recall: 9/9 (1.0);
- hard failures: 0.

The evaluator result is a development quality signal, not a production acceptance criterion. The gold fixture is intentionally non-exhaustive, so 100% Event/Claim recall does not imply semantic perfection or precision.

## Contract v0.2 refinement derived from the real bundle

The first real contract-first run showed that production completeness was much better than the earlier coverage experiments, while also exposing Contract-level quality issues that should not be solved by a second extraction engine:

- most Events had `time: null` even though the source explicitly provides or safely inherits traditional months; Contract v0.2 therefore requires Event source-time retention while keeping normalized Gregorian month/day null;
- `公到新野` had been represented with `returned_to`, and `公进军江陵` with `sent_forces`; Contract v0.2 therefore forbids merely-related predicate fallback;
- assertions such as `使统本兵` may not fit the current vocabulary faithfully; the agent should emit `ontology_gap` rather than force the assertion into `supported` or another approximate predicate;
- a combined `曹操征刘备至巴丘并遣张憙救合肥` Event contained multiple independently meaningful timeline actions; Contract v0.2 strengthens the atomic boundary rule;
- bounded repair added a `夏口` Entity but left a warning saying `夏口` was not materialized; repair must keep warnings consistent with the corrected final bundle;
- `--initial-output` preserves the normalized pre-repair bundle so future repair changes can be audited directly.

`江南诸郡` vs broader `江南`, and `江夏太守` vs jurisdictional `江夏`, remain resolution/granularity questions rather than extraction hard failures.

## Repair safety incident — first Contract v0.2 run

The first real Contract v0.2 run produced a substantial initial extraction:

```text
initial counts = 31 entities / 29 events / 23 claims / 5 warnings
initial validator errors = 4
```

The old full-bundle repair protocol then returned only:

```text
0 entities / 2 events / 2 claims / 0 warnings
```

That candidate still had 7 dangling-reference errors. This demonstrated that a model instructed to return a complete corrected bundle can accidentally interpret bounded repair as “return only corrected records,” causing catastrophic record loss.

This is a repair-protocol failure, not an extraction/Contract failure. The production design was therefore tightened to `patch-only-v0.2`:

- the model returns only targeted `replace`, `add`, and `remove_warning_messages` operations;
- deterministic code applies those operations to a copy of the initial bundle;
- no unmentioned historical record can disappear;
- existing Source/Entity/Event/Claim identities cannot be deleted or silently replaced;
- duplicate new temp IDs and unknown replacement targets are rejected;
- the resulting candidate is revalidated deterministically;
- `--output` is produced only if revalidation passes;
- a failed candidate may be saved only through `--repair-candidate-output` for diagnostics.

## Decision from Coverage v0.2 experiments

Coverage v0.2 was useful as an experiment because it exposed real failure modes: omitted source actions, Event/Claim granularity problems, pass-2 regressions, object explosion, and traditional source-month mistakes. It also demonstrated that turning coverage into an increasingly detailed semantic audit duplicates the extraction agent's historical-understanding responsibility.

Therefore Coverage v0.2 is not part of the production ingestion architecture. Its code and measurements remain available as research evidence; C0-T5 is the production direction.
