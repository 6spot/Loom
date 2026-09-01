---
task: C0-T6
issue: 467
status: completed
depends_on: [C0-T5]
created_at: 2026-09-01
started_at: 2026-09-01
completed_at: 2026-09-01
completion_pr: 459
merge_sha: 2e6dec7689bccfd4fc409a4a0486824d4bcb5791
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

The raw fixture was committed without `expected.yaml`. Human gold may be added only after the first production run and only as a development benchmark.

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
- [x] the same Contract v0.2/config/schema are used with no fixture-specific code path;
- [x] production extraction runs with no Coverage pass;
- [x] final deterministic validation passes after at most one patch-only repair;
- [x] failed repair cannot overwrite staged output by pipeline design;
- [x] explicit/inherited source time is retained conservatively;
- [x] `十三年春` does not leak into later `是岁` records;
- [x] Event boundaries and predicate choices were manually reviewed for source fidelity;
- [x] ontology gaps are surfaced rather than hidden behind nearby predicates;
- [x] the only ontology expansion from this run (`retreat` Event type) is supported independently by both fixtures;
- [x] the exact saved second-source initial bundle validates directly with zero hard failures after adding `retreat` to the shared Event vocabulary;
- [x] optional human-gold evaluation remains development-only and was not used for the production run;
- [x] full prototype unittest discovery remains green after the cross-source ontology update;
- [x] delivery PR / CI / merge reconciliation completed.

## Real Luna verification — second source

The unchanged production pipeline was run against the second fixture with `gpt-5.6-luna`.

Initial extraction:

```text
38 entities / 28 events / 25 claims / 4 warnings
initial validator errors = 1
```

The only deterministic error was:

```text
events/27/type: 'retreat' is not in the allowed Event type vocabulary
```

Patch-only repair performed exactly one targeted Event replacement and preserved all object counts:

```text
initial:   38 / 28 / 25 / 4
candidate: 38 / 28 / 25 / 4
output:    38 / 28 / 25 / 4

replaced events = 1
replaced claims = 0
replaced entities = 0
added records = 0
removed warnings = 0
final validator errors = 0
result = PASS
```

This independently confirms the repair-safety behavior first validated on the 武帝纪 fixture.

## Time inheritance result

The second source gives `十三年春` only for the opening Huang Zu campaign and then broadens to `是岁` narration. Contract v0.2 handled this conservatively:

- Events 1–8 (Huang Zu campaign) carry `season=spring`, Jian'an 13, normalized year 208;
- Events 9–28 carry Jian'an 13 / normalized year 208 but `season=null` and `month=null`;
- no later Red Cliffs, Liu Biao/Liu Cong, South Commandery, or Hefei Event inherited `spring` incorrectly;
- normalized Gregorian month/day remain null throughout because no verified converter is present.

This is stronger evidence than the first fixture because it shows the contract can preserve an explicit season without letting that season leak into later year-level narration.

## Event / predicate review

The second-source output is broadly well-shaped rather than clause-exploded: 28 Events cover the Huang Zu campaign, administration, Liu Biao/Liu Cong, Liu Bei/Sun Quan coordination, Red Cliffs, South Commandery/Yiling, and Hefei.

Useful observations:

- contextual coreference with `权` as Sun Quan worked without any fixture-specific rule;
- ontology gaps were explicitly surfaced for Lu Su's request/message role, counsel/opposition around whether to receive Cao Cao, and related source assertions not faithfully represented by the current Claim predicates;
- `partial_calendar_conversion` was emitted with the correct warning category;
- some compound Event titles remain (for example `曹操北还并留军守地` and the administrative county/commandery split), so Event-boundary guidance is not semantically perfect, but the output is not exhibiting the earlier Coverage-style object explosion;
- no evidence from this run justifies adding source-specific rules.

## Cross-source ontology evidence: retreat

Both independent fixtures produced `retreat` as a natural Event type:

- 魏书·武帝纪: `孙权走` / `曹操引军还`;
- 吴书·吴主传: `孙权退兵`.

The original Event enum omitted `retreat`, which forced validator-driven repair to coarsen these Events to `movement`. Because the same semantic category appeared independently across both sources, `retreat` is now promoted into the controlled Event type vocabulary in both the JSON Schema and ingestion config.

This follows Chronicle's ontology-growth rule: expand from repeated real-source evidence rather than designing a universal ontology up front or tuning to one gold fixture.

After the shared vocabulary update, the exact saved second-source initial bundle was evaluated again with `--no-gold` and reported zero hard failures without rerunning extraction or repair. This confirms that the prior repair was solely compensating for the missing shared Event category rather than correcting a source-extraction error.

## Unittest follow-up

The first full prototype discovery after the ontology update ran 43 tests. Forty-two passed; one Contract prompt test failed because it asserted that the literal phrase `coverage audit` must not appear anywhere, while the production prompt intentionally contains the prohibition `do not perform a second-pass coverage audit`. The prompt behavior was correct and already cross-source validated; the test assertion was over-broad.

The test was corrected to require the explicit prohibition rather than forbid the phrase itself. After the C0-T7 resolution tests and Event-blocking regressions were added, a fresh complete discovery was run again:

```text
python3 -m unittest discover \
  -s apps/chronicle/ingestion/prototype \
  -p 'test_*.py' \
  -v
```

Result:

```text
Ran 50 tests in 0.024s
OK
```

This closes the C0-T6 full-suite follow-up: the cross-source ontology update and its prompt-test correction remain green in the complete current Chronicle prototype suite.

## What this run pressure-tested

- contextual coreference with `权` as Sun Quan rather than `公` as Cao Cao;
- a broad `十三年春` opening followed by `是岁`, testing conservative time inheritance rather than blanket season propagation;
- long military/action chains such as Huang Zu, Red Cliffs, South Commandery, Yiling, and Hefei without Event clause explosion;
- assertions such as `鲁肃乞奉命吊表二子`, `多劝权迎之`, `惟瑜、肃执拒之议`, relief/defense assignments, and administrative divisions that expose genuine predicate ontology gaps;
- independent extraction of overlapping facts such as 刘表死、刘琮降、赤壁、疫病、曹操北还、合肥 from this source rather than from the first fixture.

## Decision

Contract v0.2 has now passed a meaningful cross-source production test without fixture-specific extraction code and without a Coverage pass. Do not continue tuning the prompt around either single fixture.

The next useful work should move upward in the data lifecycle: begin source-independent resolution/linking of overlapping Entity/Event representations across the two independently ingested bundles. Human gold may still be added later for benchmark purposes, but it is no longer required to justify the production architecture.

## Completion verification

Delivery PR #459 merged to `main` on 2026-09-01 as `2e6dec7689bccfd4fc409a4a0486824d4bcb5791`. The repository's current GitHub Actions path filters do not include Chronicle/Python, so no Chronicle GitHub CI pass is claimed; the full 50-test repository checkout run is the applicable suite evidence.
