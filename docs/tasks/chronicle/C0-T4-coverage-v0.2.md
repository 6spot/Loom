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
- derive deterministic textual-order audit units from the source and require one coverage decision for every unit;
- require `covered` audit decisions to cite an existing pass-1 Event or Claim; Entity presence alone is not sufficient evidence of action/state coverage;
- require `gap` audit decisions to cite additions returned in the same response;
- return **audit + additions only** rather than a rewritten full bundle;
- deterministically merge additions into pass 1, assigning new temp IDs and rewriting references while preserving all existing pass-1 objects verbatim;
- suppress obvious duplicate entities/events/claims during merge;
- keep canonical predicate, evidence grounding, deferred resolution, and historical-time precision policies;
- expose `--coverage-pass`, `--initial-output`, and `coverage-prompt` through the unified CLI;
- provide an exact A/B runner that applies coverage to an already-captured pass-1 staged bundle so model sampling does not confound the experiment;
- allow the independent coverage runner to persist the raw provider response for audit/debugging;
- record initial/final object counts, audit summary, and proposed/added/skipped-duplicate merge statistics in the evaluation report.

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
- [x] Coverage output protocol is audit+additions-only; pass-1 records are immutable.
- [x] Machine-derived audit units force a textual-order coverage checklist.
- [x] A `covered` decision must reference an existing pass-1 Event/Claim; Entity-only coverage is rejected.
- [x] A `gap` decision must reference one or more additions from the same patch.
- [x] Deterministic merge assigns new temp IDs, rewrites references, and preserves pass-1 objects.
- [x] Merge suppresses obvious duplicate entities/events/claims and reports merge statistics.
- [x] Unified CLI supports `--coverage-pass` and `--initial-output`.
- [x] Unified CLI can render the exact second-pass prompt with `coverage-prompt`.
- [x] `chronicle_coverage.py` can apply only the second pass to an existing Run #1 staged file for a clean A/B comparison.
- [x] `chronicle_coverage.py` can save the raw coverage provider response.
- [x] Evaluation report records coverage performed plus initial/final counts, audit summary, and merge statistics.
- [x] Unit tests for coverage prompt/audit/reviewer/merge metadata are committed.
- [ ] Full prototype unittest discovery passes in a repository checkout after the audit+additions redesign.
- [x] Exact Run #1 staged bundle was re-evaluated with refined Evaluator v2.
- [x] First Luna coverage experiment was executed over that exact Run #1 staged bundle.
- [x] First additions-only Luna pass was executed and safely preserved Run #1 but proposed zero additions.
- [ ] Luna audit+additions coverage pass is executed over that exact Run #1 staged bundle and compared against the refined baseline.
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

That experiment proved the coverage review can recover missing information such as 江夏, 文聘任职, and 孙权攻合肥, but it also demonstrated that allowing pass 2 to rewrite the complete staged bundle can destroy already-good pass-1 Claim representations and create unnecessary object growth. The protocol was therefore changed to additions-only plus deterministic merge.

The first additions-only Luna run then produced:

- hard failures: 0;
- exactly the same 14/15 entity, 10/12 event, 7/9 claim recall as Run #1;
- unchanged 27/13/10/3 object counts;
- proposed additions: 0 across all collections.

This proved pass-1 immutability works, but exposed an observability/discipline gap: the provider could return four empty arrays without proving why each source assertion was already covered. Coverage was therefore tightened again to `audit+additions-only`: every machine-derived source unit must be classified, `covered` must cite a pass-1 Event/Claim, and `gap` must cite new additions. The independent runner can now save the raw provider response.

Isolated audit-protocol regression tests: 7/7 passed, including rejection of Entity-only `covered` decisions and pass-1 immutability.

## Progress log

- 2026-08-31 — Started after Luna Run #1 produced zero hard failures but missed explicit coverage such as the Hefei attack and Wen Ping appointment in the current gold fixture.
- 2026-08-31 — Implemented a provider-neutral second pass rather than adding source-specific extraction rules.
- 2026-08-31 — Added an existing-staged coverage runner so the first Luna output can be held fixed while only Coverage v0.2 changes.
- 2026-08-31 — Refined Run #1 measured 14/15 entities, 10/12 events, and 7/9 claims with zero hard failures.
- 2026-08-31 — First full-bundle coverage run improved entity/event recall but reduced Claim recall and expanded 13 events to 29; redesigned coverage as additions-only with deterministic merge so pass-1 data cannot regress.
- 2026-08-31 — First additions-only run safely preserved Run #1 but returned zero additions; redesigned the protocol as auditable coverage units plus additions so a zero-addition result must prove Event/Claim coverage unit by unit.
