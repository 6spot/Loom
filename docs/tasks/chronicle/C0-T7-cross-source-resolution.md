---
task: C0-T7
issue: 468
status: in_progress
depends_on: [C0-T6]
created_at: 2026-09-01
started_at: 2026-09-01
completed_at:
completion_pr:
merge_sha:
---

# Chronicle cross-source resolution / linking

## Goal

Add the first Chronicle layer that can relate independently ingested source-owned Entity/Event records without rewriting, merging, or deleting the staged source bundles.

## Architecture

```text
staged source bundle A ─┐
                        ├─ deterministic candidate blocking
staged source bundle B ─┘
                                  ↓
                         candidate Entity/Event pairs
                                  ↓
                         closed-world resolver agent
                                  ↓
                         Resolution Link records
```

Resolution links are derived application records. They are not replacements for source records and they do not assign canonical UUIDs in C0-T7.

## Core invariant

```text
Source-owned staged records remain immutable.
Resolution creates links; it does not overwrite history.
```

A later publication layer may use accepted links to construct canonical UUIDv7 records, but that authority is explicitly outside this task.

## Candidate blocking

Deterministic code may reduce the pair search space but must not make semantic identity decisions.

### Entity candidates

V0 candidate rule:

- same Entity `type`;
- at least one exact stable surface shared across `canonical_name`, aliases, or non-contextual mentions.

This is only a candidate signal. Same name does not prove same identity.

### Event candidates

V0 blocks Events only when source time is compatible and the records share meaningful structural signals such as:

- compatible Event type + shared participant;
- multiple shared participants;
- shared participant + shared place.

`movement` / `retreat` and `military` / `battle` are candidate-blocking compatibility groups only; they do not imply occurrence identity.

## Resolver decisions

Entity:

- `same_entity`
- `not_same`
- `uncertain`

Event:

- `same_occurrence`
- `related_occurrence`
- `not_same`
- `uncertain`

`same_occurrence` is deliberately stricter than historical relatedness. Two Events in the same campaign or causal chain may be `related_occurrence` rather than the same Event.

Resolver confidence describes confidence in the resolution decision only; it is not historical truth confidence.

## Model safety boundary

The model receives only candidate records/signals and returns:

```json
{
  "entity_decisions": [
    {
      "candidate_id": "ec_001",
      "decision": "same_entity",
      "confidence": 0.98,
      "rationale": "..."
    }
  ],
  "event_decisions": []
}
```

The model cannot choose or rewrite source refs. Deterministic code reattaches the original `left/right` refs from the candidate set.

The model must return every candidate exactly once, may not invent candidate IDs, and may not invent canonical UUIDs.

## Scope

- add `chronicle-resolution-v0.1.schema.json`;
- add deterministic Entity/Event candidate generation;
- add closed-world resolver prompt and decision protocol;
- add `chronicle_resolve.py` for two staged bundle files;
- add offline unit tests;
- first real run should use the independently ingested 武帝纪 and 吴主传 bundles;
- no human gold is a resolver input;
- no canonical publication or persistence in this task;
- no Loom Core/Runtime/Storage changes.

## Non-goals

- assigning canonical UUIDs;
- destructive deduplication;
- deciding historical truth among conflicting sources;
- universal fuzzy name matching;
- source-specific matching rules;
- N-way corpus clustering beyond the first pairwise linking prototype.

## Acceptance

- [x] issue #468 records the resolution boundary.
- [x] machine-readable resolution-link schema exists.
- [x] deterministic Entity candidate blocking exists.
- [x] deterministic Event candidate blocking exists.
- [x] resolver agent only adjudicates supplied candidates.
- [x] final left/right refs are reconstructed deterministically rather than trusted from model output.
- [x] final protocol distinguishes same occurrence from related occurrence.
- [x] offline tests are committed.
- [ ] full prototype unittest discovery is green with resolution tests.
- [ ] real 武帝纪 ↔ 吴主传 candidate set is inspected.
- [ ] real resolver run links overlapping Entities/Events without modifying either input bundle.
- [ ] resolution output passes the resolution-link JSON Schema.
- [ ] delivery PR / CI / merge reconciliation completed.

## First real validation targets

The resolver should have enough source-bounded evidence to propose links for some of the overlapping records already extracted independently, for example:

- Entities: 曹操、孙权、刘备、刘表、刘琮、周瑜、程普、鲁肃、合肥、赤壁;
- Events: 刘表死、刘琮降曹、赤壁相关战事、曹操退却/北还、孙权合肥行动.

Not every overlapping-looking pair must become `same_occurrence`. In particular, coarse source Event boundaries may cause one record to be related to several records in the other source. V0 should preserve that ambiguity instead of forcing a one-to-one merge.
