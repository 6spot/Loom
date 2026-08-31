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

- keep model-v0 pass 1 unchanged;
- optionally perform one coverage-v0.2 provider call after pass 1;
- give coverage-v0.2 only source text, document context, ingestion config, JSON Schema, and the pass-1 staged bundle;
- audit explicit historically meaningful actions/state changes in source order;
- preserve valid pass-1 records and add only source-supported missing records;
- keep canonical predicate, evidence grounding, deferred resolution, and historical-time precision policies;
- normalize the revised full bundle through the existing model transport normalizer;
- expose `--coverage-pass`, `--initial-output`, and `coverage-prompt` through the unified CLI;
- record initial/final object counts in the evaluation report for A/B comparison.

## Non-goals

- fixture-specific rules for 孙权攻合肥 or 文聘任江夏太守;
- human-gold/reference data in either model prompt;
- automatic canonical entity resolution;
- event deduplication;
- production model vendor selection;
- Loom Core/Runtime/Storage changes.

## Acceptance

- [x] Coverage-v0.2 prompt is source-grounded and includes pass-1 staged data.
- [x] Coverage prompt has no `expected.yaml`/gold input path.
- [x] Coverage reviewer returns a complete revised staged bundle and reuses model transport normalization.
- [x] Unified CLI supports `--coverage-pass` and `--initial-output`.
- [x] Unified CLI can render the exact second-pass prompt with `coverage-prompt`.
- [x] Evaluation report records coverage performed plus initial/final counts.
- [x] Unit tests for coverage prompt/reviewer/count metadata are committed.
- [ ] Full prototype unittest discovery passes in a repository checkout.
- [ ] Luna Run #2 with coverage-v0.2 is executed and compared against Run #1.
- [ ] Delivery PR / CI / merge reconciliation completed.

## Progress log

- 2026-08-31 — Started after Luna Run #1 produced zero hard failures but missed explicit coverage such as the Hefei attack and Wen Ping appointment in the current gold fixture.
- 2026-08-31 — Implemented a provider-neutral second pass rather than adding source-specific extraction rules. The pass preserves valid first-pass output and audits explicit source actions/state changes sentence-by-sentence.
