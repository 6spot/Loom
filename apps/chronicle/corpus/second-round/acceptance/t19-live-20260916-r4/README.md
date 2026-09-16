## LM-80 acceptance rerun (2026-09-16, r4)

This directory records the remaining acceptance gaps against the PR's
product-code head `c4b1fd04eb5ae71249894a9ebbd9daa7b7acea40`. The follow-up
evidence commit only adds these records and does not change product behavior.

### Results

- `fixture-gate/manifest.json` is a fresh current-head Compose run with
  `result=PASS`, browser-required coverage, 5,000 synthetic units and 1,000
  groups. Its manifest retains the explicit fixture-only disclaimer.
- `edition/old-session.json` is a fresh current-head product-persistence/API
  check (fixture data inserted through the product persistence API, with no raw
  SQL): a 4-paragraph edition was appended to six paragraphs; the old version
  remained readable with the same page digest and ordinals `[0,1,2,3]`, while
  the new page exposed appended ordinals `[4,5]`.
- `background/background-result.json` records the real Rust web + Python read
  sidecar + PostgreSQL browser flow. It covers unsaved invisibility, exact
  range display, outside-range paper, overlap/wrong-version/transport failure
  draft retention, disable, and restart persistence. The generated stack was
  cleaned up after the run.
- `routing.json` pairs deterministic automatic/exception route coverage with
  the preserved r3 real-material human-review evidence. It does not turn the
  fixture route into a live provider-quality claim.

The prior r3 real-data success/failure artifacts remain untouched in
`../t19-live-20260916-r3/`: provider outputs, invalid extraction/linking and
context-limit records, human acceptance, publication, content checks, and
public readback.

### Gate scope

The fixture gate is a product-contract gate, not a substitute for the r3
real-data content judgment. The final PR/CI gate result is reported in the
Multica handoff comment from the latest head.
