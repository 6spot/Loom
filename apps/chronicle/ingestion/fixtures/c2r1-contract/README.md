# c2r1-contract fixtures (C2-R1-T01)

Contract examples owned by C2-R1-T01 for downstream tasks
(T03/T04/T05/T06/T07/T15). All files are **contract fixtures, not real
historical answers**: surfaces reuse classical names only to exercise
occurrence/alias/anchor rules.

- `request.json` — program-owned chapter request (hashes, blocks, required
  coverage, limits). Never model-generated.
- `candidate-valid.json` — passing `chronicle.chapter-candidate / 0.1`.
  Same-chapter 曹操/操 share `ent_001`; 公/王 stay contextual mentions;
  ambiguous `m_004` carries no forced target.
- `artifact-accepted.json` — `chronicle.chapter-artifact / 0.1` produced by
  `accept_chapter_candidate` (anchors, fingerprint, producing run).
- `candidate-*.json` / `request-hash-drift.json` — negative contract
  examples, each rejected by `validate_chapter_candidate`.
- `resolution-v02-within-revision.json` — structural `resolution-links /
  0.2` example (no auto-derived same-links; T08 owns business rules).
- `assembled-mapping-example.json`, `chapter-pair-context-example.json`,
  `batch-context-example.json`, `public-chapter-response-example.json`,
  `public-source-response-example.json`, `review-page-example.json` —
  shared DTO shapes for assembly/review/public/queue consumers.
