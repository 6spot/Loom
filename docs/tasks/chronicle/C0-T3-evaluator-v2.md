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
- add non-title Event matching using type, time, participants, roles, and places;
- add Claim matching that tolerates temp-ID changes, predicate aliases, and different exact source evidence spans;
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
- [x] Event matching does not use title as identity.
- [x] Claim matching tolerates evidence-span containment and configured predicate aliases.
- [x] Extra source-grounded entities are reported as additional output, not hard failures.
- [x] Hard checks cover grounding, references, time precision, predicate vocabulary, and initial assessment.
- [ ] Unified model-v0 CLI emits v0.2 evaluation reports.
- [ ] Full prototype unittest discovery passes in a repository checkout.
- [ ] First Luna extraction is replayed through evaluator v2 and recorded.
- [ ] Delivery PR / CI / merge reconciliation completed.

## Progress log

- 2026-08-31 — Started after first real `gpt-5.6-luna` Chronicle extraction completed with schema-valid output but 73 exact-comparator mismatches. The result showed that many mismatches were title/predicate/granularity differences or extra source-grounded material rather than extraction failures.
