---
task: C0-T3
issue: 464
status: in_progress
depends_on: [C0-T2]
created_at: 2026-08-31
started_at: 2026-08-31
completed_at:
completion_pr:
merge_sha:
---

# Chronicle evaluator v2

## Goal

Replace exact-title/exact-predicate gold mismatch counting with a useful model-ingestion evaluation that separates provable hard failures from semantic representation differences.

## Scope

- add hard checks for source grounding, reference integrity, traditional-calendar fake precision, configured Claim predicate vocabulary, and initial Claim assessment;
- add non-title Event matching using type, time, participants, roles, places, and weak same-type source-title evidence;
- add Claim matching that tolerates temp-ID changes, predicate aliases, evidence-span differences, compatible literal/value surface granularity, and conservative composite atomic coverage;
- treat the current human gold fixture as non-exhaustive;
- report gold recall plus additional output instead of fake precision;
- add a small controlled Claim predicate vocabulary to `chronicle-v0.1.yaml` based on observed real extraction output;
- make model-v0 `--report` emit evaluation version 0.2;
- keep `rules-v0` exact regression comparison unchanged.

## Non-goals

- semantic embedding evaluation;
- LLM-as-judge evaluation;
- declaring extra source-grounded entities/events/claims incorrect solely because they are absent from the current gold fixture;
- final universal historical predicate ontology;
- changes to Loom Core/Runtime/Storage.

## Acceptance

- [x] Evaluator v2 module exists.
- [x] Predicate vocabulary and backward-compatible aliases are configured.
- [x] Model predicate output policy is canonical-only.
- [x] Event matching does not use title as identity.
- [x] Empty participant/place fields do not create false semantic similarity.
- [x] Raw/normalized same-type Event titles can contribute weak semantic evidence (for example `于是大疫…` vs `曹操军发生大疫`).
- [x] Claim matching tolerates evidence-span containment and configured predicate aliases.
- [x] Compatible literal/value surface differences such as `不利` vs `曹操军不利` can match.
- [x] Conservative composite Claim coverage can represent one longer gold assertion using multiple atomic model Claims.
- [x] Selected granularity differences such as office Entity vs office literal are normalized for Claim comparison.
- [x] Same-type Entity surface containment can align `江南诸郡` with `江南` without collapsing `江夏太守` into place `江夏`.
- [x] Extra source-grounded entities are reported as additional output, not hard failures.
- [x] Hard checks cover grounding, references, time precision, predicate vocabulary, and initial assessment.
- [x] Unified model-v0 CLI emits v0.2 evaluation reports.
- [x] Existing staged output can be re-evaluated without invoking a model.
- [x] First Luna extraction was replayed through evaluator v2 and recorded.
- [ ] Full prototype unittest discovery passes in a repository checkout after the latest refinements.
- [ ] Delivery PR / CI / merge reconciliation completed.

## Verification

First real Luna staged output replayed through Evaluator v0.2 before the latest matcher refinements:

- hard failures: `0`;
- entities: `13/15` (`0.867`) gold recall;
- events: `9/12` (`0.75`) gold recall;
- claims: `5/9` (`0.556`) gold recall;
- counts: 27 entities, 13 events, 10 claims, 3 warnings.

That replay exposed remaining evaluator false negatives: the epidemic Event appeared as `于是大疫，吏士多死者`, the outcome Claim used atomic `不利`, and `江南诸郡` represented a finer source-grounded place surface than gold `江南`. Regression refinements were added for these cases.

Repository-side review confirms changes are isolated to Chronicle ingestion/config/task files; no Loom Core/Runtime/Storage files were modified.

Local isolated refinement tests and Python compilation passed before commit. Full committed unittest discovery remains pending in a real repository checkout.

## Progress log

- 2026-08-31 — Started after first real `gpt-5.6-luna` Chronicle extraction completed with schema-valid output but 73 exact-comparator mismatches.
- 2026-08-31 — Implemented deterministic Evaluator v2 hard checks, structured Event/Claim matching, non-exhaustive gold-recall reporting, canonical Claim predicate policy, and `chronicle_cli.py evaluate`.
- 2026-08-31 — Replayed the exact first Luna staged bundle: zero hard failures and 0.867/0.75/0.556 entity/event/claim gold recall.
- 2026-08-31 — Refined Event title evidence, literal/value containment, same-type Entity surface matching, and conservative composite Claim coverage based on the replay rather than changing the model to imitate gold wording.
