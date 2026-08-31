---
task: C0-T4
issue: 465
status: in_progress
depends_on: [C0-T2, C0-T3]
created_at: 2026-08-31
started_at: 2026-08-31
completed_at:
completion_pr:
merge_sha:
---

# Chronicle extraction coverage v0.2

## Goal

Add a second closed-book model review that improves extraction coverage without teaching the model the human-gold answer or adding fixture-specific phrase rules.

## Scope

- keep model-v0 pass 1 unchanged and immutable;
- optionally perform one coverage-v0.2 provider call after pass 1;
- give coverage-v0.2 only source text, document context, ingestion config, JSON Schema, and the pass-1 staged bundle;
- audit explicit historically meaningful actions/state changes in source order;
- return **additions only** (`entities`, `events`, `claims`, `warnings`) rather than a rewritten full bundle;
- deterministically merge additions into pass 1, assigning new temp IDs and rewriting references while preserving all existing pass-1 objects verbatim;
- suppress obvious duplicate entities/events/claims during merge;
- keep canonical predicate, evidence grounding, deferred resolution, and historical-time precision policies;
- expose `--coverage-pass`, `--initial-output`, and `coverage-prompt` through the unified CLI;
- provide an exact A/B runner that applies coverage to an already-captured pass-1 staged bundle so model sampling does not confound the experiment;
- record initial/final object counts plus proposed/added/skipped-duplicate merge statistics in the evaluation report.

## Non-goals

- fixture-specific rules for 孙权攻合肥 or 文聘任江夏太守;
- human-gold/reference data in either model prompt;
- automatic canonical entity resolution;
- final event deduplication/publication semantics;
- production model vendor selection;
- Loom Core/Runtime/Storage changes.

## Acceptance

- [x] Coverage-v0.2 prompt is source-grounded and includes pass-1 staged data.
- [x] Coverage prompt has no `expected.yaml`/gold input path.
- [x] Coverage output protocol is additions-only; pass-1 records are immutable.
- [x] Deterministic merge assigns new temp IDs, rewrites references, and preserves pass-1 objects.
- [x] Merge suppresses obvious duplicate entities/events/claims and reports merge statistics.
- [x] Unified CLI supports `--coverage-pass` and `--initial-output`.
- [x] Unified CLI can render the exact second-pass prompt with `coverage-prompt`.
- [x] `chronicle_coverage.py` can apply only the second pass to an existing Run #1 staged file for a clean A/B comparison.
- [x] Evaluation report records coverage performed plus initial/final counts and merge statistics.
- [x] Unit tests for coverage prompt/reviewer/merge metadata are committed.
- [ ] Full prototype unittest discovery passes in a repository checkout after the additions-only redesign.
- [x] Exact Run #1 staged bundle was re-evaluated with refined Evaluator v2.
- [x] First Luna coverage experiment was executed over that exact Run #1 staged bundle.
- [ ] Luna additions-only coverage pass is executed over that exact Run #1 staged bundle and compared against the refined baseline.
- [ ] Delivery PR / CI / merge reconciliation completed.

## Verification

Refined Luna Run #1 baseline over the exact staged bundle:

- hard failures: 0;
- entities: 14/15 gold recall (0.933);
- events: 10/12 gold recall (0.833);
- claims: 7/9 gold recall (0.778);
- counts: 27 entities / 13 events / 10 claims / 3 warnings.

First Coverage v0.2 experiment used the original full-bundle rewrite protocol:

- hard failures: 0;
- entities: 15/15 (1.0);
- events: 11/12 (0.917);
- claims: 6/9 (0.667);
- counts grew from 27/13/10 to 33/29/26.

That experiment proved the coverage review can recover missing information such as 江夏, 文聘任职, and 孙权攻合肥, but it also demonstrated that allowing pass 2 to rewrite the complete staged bundle can destroy already-good pass-1 Claim representations and create unnecessary object growth. The protocol was therefore changed to additions-only plus deterministic merge before the next A/B run.

## Progress log

- 2026-08-31 — Started after Luna Run #1 produced zero hard failures but missed explicit coverage such as the Hefei attack and Wen Ping appointment in the current gold fixture.
- 2026-08-31 — Implemented a provider-neutral second pass rather than adding source-specific extraction rules.
- 2026-08-31 — Added an existing-staged coverage runner so the first Luna output can be held fixed while only Coverage v0.2 changes.
- 2026-08-31 — Refined Run #1 measured 14/15 entities, 10/12 events, and 7/9 claims with zero hard failures.
- 2026-08-31 — First full-bundle coverage run improved entity/event recall but reduced Claim recall and expanded 13 events to 29; redesigned coverage as additions-only with deterministic merge so pass-1 data cannot regress.
