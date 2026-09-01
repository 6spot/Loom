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

V0 requires compatible source time and then uses conservative structural evidence.

Broad Event families such as `military` / `battle` / `movement` require both:

- at least one shared participant; and
- at least one shared place.

Narrow Event types such as `death`, `birth`, `surrender`, `retreat`, and `epidemic` may qualify with the same exact type plus a shared participant even when one source omits place detail.

Two or more shared participants also qualify a pair for semantic adjudication. Explicitly conflicting season/month values reject a pair when both sources provide them.

Candidate blocking is deliberately recall-oriented but should not admit pairs merely because a high-frequency actor appears in both records in the same year.

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
- [x] real 武帝纪 ↔ 吴主传 candidate set is inspected.
- [x] real resolver run links overlapping Entities/Events without modifying either input bundle.
- [x] resolution output passes the resolution-link JSON Schema.
- [ ] delivery PR / CI / merge reconciliation completed.

## First real validation

The first independently extracted 武帝纪 ↔ 吴主传 run initially produced 10 Entity candidates and 42 Event candidates. Inspection showed that the Event blocking was too permissive: same year + one high-frequency actor + a broad compatible type admitted unrelated actions.

After tightening the generic blocking rule, without source-specific exceptions, the same two bundles produced:

```text
Entity candidates: 10
Event candidates: 10
```

The retained Event candidate set covered:

- 赤壁之战 ↔ 赤壁之战;
- 刘琮降 ↔ 刘琮率众向曹操投降;
- 刘备走夏口 ↔ 刘备进驻夏口;
- 曹操进军江陵 ↔ 曹操北还并留军守江陵、襄阳;
- 孙权攻合肥 ↔ 孙权围攻合肥;
- 孙权攻合肥 ↔ 曹军未至合肥孙权退兵;
- 遣张憙救合肥 ↔ 曹操遣张喜率骑兵赴合肥;
- 刘表卒 ↔ 刘表去世;
- 孙权退走 ↔ 孙权攻合肥逾月不下而退;
- 曹操引军还 ↔ 曹操焚余船引退.

The first real closed-world resolver run passed the resolution JSON Schema and returned:

```text
Entities:
  same_entity: 5
  uncertain:   5

Events:
  same_occurrence:    8
  related_occurrence: 2
```

The five person links (曹操、刘表、刘琮、刘备、孙权) were `same_entity`. The five place links (襄阳、夏口、江陵、赤壁、合肥) remained `uncertain` because the supplied candidate evidence contained only same type + same stable surface and no stronger identity signal. This is preferred to treating same-name places as proven identity.

The two `related_occurrence` Event decisions were:

- 曹操进军江陵 ↔ 曹操北还并留军守江陵、襄阳;
- 孙权攻合肥 ↔ 曹军未至合肥孙权退兵.

All other retained Event pairs were resolved as `same_occurrence`.

A useful emergent signal appeared in `遣张憙救合肥 ↔ 曹操遣张喜率骑兵赴合肥`: Event resolution judged the pair `same_occurrence` even though `张憙` and `张喜` did not pass conservative Entity blocking. This suggests a later task can use accepted same-occurrence links to propose additional Entity-resolution candidates without weakening first-pass fuzzy-name blocking.

## First real validation targets

The resolver should have enough source-bounded evidence to propose links for some of the overlapping records already extracted independently, for example:

- Entities: 曹操、孙权、刘备、刘表、刘琮、合肥、赤壁;
- Events: 刘表死、刘琮降曹、赤壁相关战事、曹操退却/北还、孙权合肥行动.

Not every overlapping-looking pair must become `same_occurrence`. In particular, coarse source Event boundaries may cause one record to be related to several records in the other source. V0 should preserve that ambiguity instead of forcing a one-to-one merge.
