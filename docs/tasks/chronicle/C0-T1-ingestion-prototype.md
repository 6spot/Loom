---
task: C0-T1
issue: 462
status: in_progress
depends_on: []
created_at: 2026-08-31
started_at: 2026-08-31
completed_at:
completion_pr:
merge_sha:
---

# Chronicle V0 ingestion prototype

## Goal

Prove the first Chronicle ingestion vertical slice without introducing a fake general-purpose historical extractor.

The stable boundary under test is:

`raw text + document context -> extractor -> Chronicle v0.1 staged bundle -> JSON Schema validation -> human-gold comparison`

## Scope

- keep implementation isolated under `apps/chronicle/ingestion/`;
- provide a deterministic `rules-v0` extractor for the committed `sanguozhi-wudi-jianan-13` fixture;
- emit `Source`, `Entity`, `Event`, and `Claim` staged objects with job-local `temp_id` values;
- preserve traditional calendar month expressions while normalizing only the safe regnal-year mapping to 208;
- validate staged output with the committed Draft 2020-12 schema;
- compare stable semantics with `expected.yaml` while ignoring extractor-only diagnostics;
- provide unit tests and documented commands.

## Non-goals

- general LLM-backed extraction;
- entity resolution to canonical UUIDv7 identities;
- event deduplication or merge;
- PostgreSQL publishing;
- traditional-calendar month/day conversion to Gregorian dates;
- Loom Core/Runtime/Storage semantic changes.

## Acceptance

- [x] Runnable prototype CLI is implemented.
- [x] Deterministic fixture extractor emits the expected 12 events and 9 claims for the selected vertical slice.
- [x] Schema validation reports malformed staged data.
- [x] Gold comparison reports named missing/unexpected/different objects.
- [x] Unit tests cover extraction, validation, comparison, and mismatch reporting.
- [ ] Full committed fixture run is verified in a repository checkout with prototype dependencies installed.
- [ ] Delivery PR / CI / merge reconciliation completed.

## Progress log

- 2026-08-31 — Started after Chronicle v0.1 data contract and gold fixture were committed on `chronicle/bootstrap`. Issue #462 created as the collaboration surface.
- 2026-08-31 — Chose a deliberately fixture-scoped deterministic extractor so the downstream cleaning/validation contract can be tested without conflating this task with general historical AI extraction.
