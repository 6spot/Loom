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
- audit Claim coverage separately from overall/Event coverage; an Event does not substitute for a Claim;
- require a new Claim when an allowed canonical predicate can faithfully represent an uncovered source assertion;
- allow Claim `not_applicable` only when the configured predicate vocabulary cannot faithfully express the assertion;
- derive source-calendar month hints only from explicit textual month markers and inheritance, without Gregorian conversion;
- reject added Event/Claim records whose `chinese_lunisolar_regnal` source month conflicts with the source unit month hint;
- require `gap` audit decisions to cite additions returned in the same response;
- return **audit + additions only** rather than a rewritten full bundle;
- deterministically merge additions into pass 1, assigning new temp IDs and rewriting references while preserving all existing pass-1 objects verbatim;
- suppress obvious duplicate entities/events/claims during merge;
- keep canonical predicate, evidence grounding, deferred resolution, and historical-time precision policies;
- provide an exact A/B runner over an already-captured pass-1 staged bundle;
- allow the independent coverage runner to persist the raw provider response;
- record initial/final object counts, overall audit summary, Claim audit summary, and proposed/added/skipped-duplicate merge statistics.

## Non-goals

- fixture-specific rules for 孙权攻合肥 or 文聘任江夏太守;
- human-gold/reference data in either model prompt;
- automatic canonical entity resolution;
- verified traditional-calendar to Gregorian month/day conversion;
- final event deduplication/publication semantics;
- production model vendor selection;
- Loom Core/Runtime/Storage changes.

## Acceptance

- [x] Coverage-v0.2 prompt is source-grounded and includes pass-1 staged data.
- [x] Coverage prompt has no `expected.yaml`/gold input path.
- [x] Coverage output protocol is audit+additions-only; pass-1 records are immutable.
- [x] Machine-derived audit units force a textual-order coverage checklist.
- [x] A `covered` decision must reference an existing pass-1 Event/Claim; Entity-only coverage is rejected.
- [x] Claim coverage is audited independently; Event presence cannot satisfy Claim coverage.
- [x] Claim gaps must reference new Claim records in the same patch.
- [x] Source-month hints are derived from explicit traditional-calendar text only.
- [x] Added Event/Claim source months that conflict with inherited source context are rejected before merge.
- [x] A `gap` decision must reference one or more additions from the same patch.
- [x] Deterministic merge assigns new temp IDs, rewrites references, and preserves pass-1 objects.
- [x] Merge suppresses obvious duplicate entities/events/claims and reports merge statistics.
- [x] `chronicle_coverage.py` can apply only the second pass to an existing Run #1 staged file for a clean A/B comparison.
- [x] `chronicle_coverage.py` can save the raw coverage provider response.
- [x] Evaluation report records coverage performed plus initial/final counts, audit summaries, and merge statistics.
- [x] Claim/time grounding regression tests are committed.
- [ ] Full prototype unittest discovery passes in a repository checkout after the latest claim/time grounding revision.
- [x] Exact Run #1 staged bundle was re-evaluated with refined Evaluator v2.
- [x] First Luna full-bundle coverage experiment was executed.
- [x] First Luna additions-only experiment was executed and safely preserved Run #1 but proposed zero additions.
- [x] First Luna audit+additions response was captured and inspected.
- [ ] Luna claim-aware audit+additions pass is executed over the exact Run #1 bundle and compared against the refined baseline.
- [ ] Delivery PR / CI / merge reconciliation completed.

## Verification

Refined Luna Run #1 baseline over the exact staged bundle:

- hard failures: 0;
- entities: 14/15 gold recall (0.933);
- events: 10/12 gold recall (0.833);
- claims: 7/9 gold recall (0.778);
- counts: 27 entities / 13 events / 10 claims / 3 warnings.

First full-bundle Coverage v0.2 experiment:

- hard failures: 0;
- entities: 15/15 (1.0);
- events: 11/12 (0.917);
- claims: 6/9 (0.667);
- counts grew from 27/13/10 to 33/29/26.

This proved the model could recover missing information, but complete-bundle rewriting damaged already-good pass-1 Claims and created unnecessary growth. Coverage therefore became additions-only with deterministic merge.

The first additions-only Luna run then produced zero additions and exactly preserved the Run #1 baseline. This proved pass-1 immutability, but the provider could still claim that nothing was missing without showing its reasoning. Coverage therefore became audit+additions-only.

The first raw audit+additions Luna response successfully exposed real gaps instead of returning empty arrays. In particular it marked the Wen Ping appointment (`u024`) and Sun Quan's Hefei attack (`u030`) as missing and proposed Events for them. However it returned `claims: []`, demonstrating that overall/Event coverage and Claim coverage were still conflated. The same response also assigned source month 9 to the added `屯襄阳` and `刘备屯樊` Events even though those clauses inherit month 8 from the source; the next explicit month 9 begins only at `公到新野`. That revealed a second unguarded failure mode: source-calendar inheritance drift.

The protocol was therefore tightened again:

- every non-context audit unit now has `claim_status`, `claim_refs`, and `claim_note`;
- allowed-predicate assertions require Claim coverage independently of Event coverage;
- audit units carry deterministic `source_month_hint` values derived only from explicit textual month markers;
- proposed Event/Claim records with a conflicting source-calendar month are rejected before merge.

Isolated claim/time protocol regression tests: 10/10 passed, including rejection of missing required Claims and rejection of an August source unit emitted as month 9.

## Progress log

- 2026-08-31 — Started after Luna Run #1 produced zero hard failures but missed explicit coverage such as the Hefei attack and Wen Ping appointment.
- 2026-08-31 — Added an existing-staged coverage runner so pass 1 can remain fixed for A/B measurement.
- 2026-08-31 — Full-bundle coverage improved entity/event recall but reduced Claim recall and expanded 13 events to 29; redesigned as additions-only.
- 2026-08-31 — First additions-only run safely preserved Run #1 but returned zero additions; added mandatory textual-order audit units.
- 2026-08-31 — Raw audit correctly identified many missing occurrences including Wen Ping's appointment and Sun Quan's Hefei attack, but proposed Events without Claims and drifted two August movement Events into September.
- 2026-08-31 — Added independent Claim coverage decisions plus deterministic source-month grounding; isolated regression suite passed 10/10.
