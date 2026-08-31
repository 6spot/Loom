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

Fixture:

```text
apps/chronicle/ingestion/fixtures/sanguozhi-wushu-wuzhu-jianan-13/
├── raw.txt
└── context.yaml
```

Source slice: 《三国志·吴书·吴主传》建安十三年, beginning `十三年春，权复征黄祖` and ending `未至，权退。`.

This source intentionally overlaps several historical occurrences already present in the 《魏书·武帝纪》 fixture while changing narrative subject, wording, event boundaries, source emphasis, and chronology granularity. It includes the Huang Zu campaign and administrative changes, Liu Biao's death and Liu Cong's surrender, Liu Bei / Sun Quan coordination, Red Cliffs, epidemic / withdrawal consequences, and Hefei.

The raw fixture is committed without `expected.yaml`. Human gold may be added only after the first production run and only as a development benchmark.

The document context supplies only stable source/document facts: Sun Quan as the narrative subject, Jian'an year 13, normalized year 208, and Chinese lunisolar/regnal source calendar. It deliberately does not set `spring` as a document-wide default because later `是岁` assertions are not mechanically constrained to spring.

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

- [x] second fixture contains source-owned `raw.txt` and explicit `context.yaml`;
- [x] second fixture has no `expected.yaml` before the production run;
- [ ] the same Contract v0.2/config/schema are used with no fixture-specific code path;
- [ ] production extraction runs with no Coverage pass;
- [ ] final deterministic validation passes directly or after at most one patch-only repair;
- [ ] failed repair cannot overwrite staged output;
- [ ] explicit/inherited source time is retained conservatively;
- [ ] `十三年春` does not leak into later `是岁` records unless the source surface safely supports that inheritance;
- [ ] Event boundaries and predicate choices are manually reviewed for source fidelity;
- [ ] ontology gaps are surfaced rather than hidden behind nearby predicates;
- [ ] any proposed Contract/predicate change is supported by evidence from both fixtures or clearly general source behavior;
- [ ] optional human-gold evaluation remains development-only;
- [ ] full prototype unittest discovery remains green;
- [ ] delivery PR / CI / merge reconciliation completed.

## What this run should pressure-test

- contextual coreference with `权` as Sun Quan rather than `公` as Cao Cao;
- a broad `十三年春` opening followed by `是岁`, testing conservative time inheritance rather than blanket season propagation;
- long military/action chains such as Huang Zu, Red Cliffs, South Commandery, Yiling, and Hefei without Event clause explosion;
- assertions such as `鲁肃乞奉命吊表二子`, `多劝权迎之`, `惟瑜、肃执拒之议`, relief/defense assignments, and administrative divisions that may expose genuine predicate ontology gaps;
- independent extraction of overlapping facts such as 刘表死、刘琮降、赤壁、疫病、曹操北还、合肥 from this source rather than from the first fixture.

## Why this source

The existing fixture is narrated from Cao Cao's biography. The selected `吴主传` passage narrates overlapping events from Sun Quan's record and frames the year as `十三年春` followed by broader `是岁` narration. This gives Chronicle a stronger generalization test than adding another Cao-Cao-centered passage: the extraction contract must handle different source emphasis and different granularity without knowing the first fixture's expected output.
