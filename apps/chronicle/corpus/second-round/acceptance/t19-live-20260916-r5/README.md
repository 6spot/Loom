## LM-80 real-provider and edition follow-up (2026-09-16, r5)

This additive directory closes the issue-level gaps identified in the independent
review of PR #749. It preserves the r3 real-material acceptance/failure records
and the r4 fixture, background, and capacity evidence.

### Real-provider routes

- `automatic-excerpt2/` is a real provider run over an exact 81-byte excerpt of
  《三國志·吳書·周瑜傳》. The chapter review produced an automatic `ai`
  acceptance, retaining the candidate, review output, request/pipeline hashes,
  and model output metadata. The required person-state follow-up was then
  resolved explicitly with five supported overrides and a stated uncertain
  default; the job reached `completed`, published a chapter, and returned a
  public detail/source readback.
- `explicit-dispute/` uses the same real source excerpt and provider profile.
  Three real resolution reviews were recorded as conservative `uncertain`
  decisions. The subsequent person-state review records a human `disputed`
  override for candidate `pf_001`, leaves the remaining candidates explicitly
  `uncertain`, then resumes through publication and public readback. This is
  an explicit exception route, not a fixture decision.
- `automatic/` preserves the full-source real-provider exception run, including
  its open content-review packet and linking/review routing outputs. The
  intentionally malformed `automatic-excerpt/` prepare failure is retained as
  a separate reproducible failure artifact. Neither is recast as an automatic
  pass.

Provider credentials are omitted. Each run records the configured provider
  identity, timeout, source hash, output hashes and durable job details; every
  route declares `fixture_substitution: false`.

### r3 publication → edition append/readback

`edition-r3/` is a real product API run. It derives two immutable
`chronicle.historical-publication` contract snapshots from the accepted r3
public chapter readback, preserving its publication ID, source SHA, artifact
SHA, revision/job IDs, block IDs and source anchors. The API lineage fields point
back to that r3 publication rather than to fixture prose.

The first edition read back nine paragraphs. An append created a new immutable
edition with the remaining nine paragraphs and accepted contiguous seam
evidence. Reading the old edition by its fixed version after the append returned
the original nine paragraphs unchanged; the new edition returned ordinals
`[9,10,11,12,13,14,15,16,17]`. The raw draft, publish and old/new public API
responses are retained alongside `summary.json`.

The r4 fixture edition remains untouched as contract/capacity evidence; this
r5 chain is the separate real-publication association requested by review.

### Gate and validation

The latest current-head staged gate was run with the required browser suite and
is recorded under `final-gate/` after the evidence commit. It passed against
commit `1c1e002cc97a7dd14e1a549d63a76dd1f0714144`, including the fixture
reading, person-state review, performance, accessibility and browser flows at
the 5,000-unit/1,000-group scale. The earlier missing-Playwright prerequisite
is preserved under `final-gate-prerequisite-failure/`; it is not presented as a
product failure. Focused persistence and staged-gate tests, JSON parsing, Python
compilation and whitespace checks are reported in the PR handoff.
