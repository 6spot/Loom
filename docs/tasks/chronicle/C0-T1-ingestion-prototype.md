---
task: C0-T1
issue: 462
status: completed
depends_on: []
created_at: 2026-08-31
started_at: 2026-08-31
completed_at: 2026-09-01
completion_pr: 459
merge_sha: 2e6dec7689bccfd4fc409a4a0486824d4bcb5791
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
- [x] Full committed fixture run is verified in a repository checkout with prototype dependencies installed.
- [x] Delivery PR / CI / merge reconciliation completed.

## Verification

- User repository checkout, 2026-08-31: `python3 -m unittest discover -s apps/chronicle/ingestion/prototype -p 'test_*.py' -v` — original rules-v0 suite 4/4 passed.
- User repository checkout, 2026-08-31: full `sanguozhi-wudi-jianan-13` command completed with `chronicle ingestion fixture passed`.
- Python syntax compilation performed during implementation — passed.
- Current repository CI has no Chronicle/Python lane; no Chronicle GitHub CI pass is claimed.
- Full current Chronicle prototype suite on 2026-09-01: `Ran 50 tests` / `OK`.
- Delivery PR #459 merged to `main` as `2e6dec7689bccfd4fc409a4a0486824d4bcb5791`.

## Progress log

- 2026-08-31 — Started after Chronicle v0.1 data contract and gold fixture were committed on `chronicle/bootstrap`. Issue #462 created as the collaboration surface.
- 2026-08-31 — Chose a deliberately fixture-scoped deterministic extractor so the downstream cleaning/validation contract can be tested without conflating this task with general historical AI extraction.
- 2026-08-31 — Implemented CLI, Draft 2020-12 validation, semantic gold comparison, tests, and prototype documentation.
- 2026-08-31 — User verified dependencies, 4/4 unit tests, and the complete committed fixture from a macOS repository checkout; the fixture ended with `chronicle ingestion fixture passed`.
- 2026-09-01 — Reconciled as completed after PR #459 merged and the current 50-test Chronicle prototype suite passed.
