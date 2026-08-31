---
task: C0-T6
issue: 467
status: in_progress
depends_on: [C0-T5]
created_at: 2026-09-01
started_at: 2026-09-01
completed_at:
completion_pr:
merge_sha:
---

# Chronicle cross-source validation

## Goal

Validate that Chronicle Contract v0.2, deterministic validation, and patch-only repair generalize to a second real historical source without adding source-specific extraction rules or reintroducing a production Coverage pass.

## Selected second source

Use a source slice from 《三国志·吴书·吴主传》十三年. This source is intentionally valuable because it overlaps several historical occurrences already present in the 《魏书·武帝纪》 fixture while changing narrative subject, wording, event boundaries, and source perspective.

The selected passage should include enough of the year-13 narrative to exercise:

- the Huang Zu campaign and administrative changes;
- Liu Biao's death and Liu Cong's surrender;
- Liu Bei / Sun Quan coordination;
- Red Cliffs;
- epidemic / withdrawal consequences;
- Hefei.

The raw fixture must be supplied as source text independently of any human gold. Human gold may be added later only as a development benchmark.

## Production experiment

```text
second raw source + document context + unchanged Contract v0.2
                         ↓
                  one extraction
                         ↓
              deterministic validator
                   ↓ pass    ↓ fail
                 staged   patch repair max 1
                              ↓
                       deterministic revalidation
```

No gold/evaluator output may be fed into extraction or repair.

## Scope

- add a second Chronicle fixture with `raw.txt` and `context.yaml`;
- run the existing `chronicle_pipeline.py` unchanged;
- preserve explicit or safely inherited source-calendar time without fabricating Gregorian month/day;
- inspect Event boundary behavior across a different narrative style;
- inspect whether predicate fidelity guidance avoids nearby semantic fallback;
- record `ontology_gap` when the controlled vocabulary cannot faithfully express source assertions;
- validate patch-only repair preservation if deterministic errors occur;
- only after production completes, optionally add human gold / Evaluator measurements;
- compare overlapping historical occurrences between the two independently ingested sources only after both outputs pass production validation;
- no Loom Core/Runtime/Storage changes.

## Non-goals

- modifying Contract v0.2 solely to improve one benchmark score;
- source-specific parser rules for `吴主传`;
- merging the two source bundles into canonical entities/events in this task;
- universal predicate ontology design;
- Gregorian lunar-calendar conversion without a verified converter.

## Acceptance

- [ ] second fixture contains source-owned `raw.txt` and explicit `context.yaml`;
- [ ] the same Contract v0.2/config/schema are used with no fixture-specific code path;
- [ ] production extraction runs with no Coverage pass;
- [ ] final deterministic validation passes directly or after at most one patch-only repair;
- [ ] failed repair cannot overwrite staged output;
- [ ] explicit/inherited source time is retained conservatively;
- [ ] Event boundaries and predicate choices are manually reviewed for source fidelity;
- [ ] ontology gaps are surfaced rather than hidden behind nearby predicates;
- [ ] any proposed Contract/predicate change is supported by evidence from both fixtures or clearly general source behavior;
- [ ] optional human-gold evaluation remains development-only;
- [ ] full prototype unittest discovery remains green;
- [ ] delivery PR / CI / merge reconciliation completed.

## Why this source

The existing fixture is narrated from Cao Cao's biography. The selected `吴主传` passage narrates overlapping events from Sun Quan's record and explicitly frames the year as `十三年春` / `是岁`. This gives Chronicle a stronger generalization test than adding another Cao-Cao-centered passage: the extraction contract must handle different source emphasis and different granularity without knowing the first fixture's expected output.
