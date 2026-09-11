# c2r2-contract fixtures (C2-R2-T01)

Contract examples owned by C2-R2-T01 for the second-round reading tasks
(T03-T17). Every file is a **contract fixture, not a historical answer**:
surfaces reuse classical names only to exercise occurrence, ambiguity,
astral-plane code-point and inheritance rules.

## Candidate / artifact

- `request.json` — program-owned chapter request (hashes, source block
  offsets, required coverage, limits). Never model-generated.
- `candidate-valid.json` — passing `chronicle.chapter-candidate / 0.2`.
  Adds `reading.units` (one per translation block) to the frozen
  first-round bundle/translation/mentions/record_sources. It exercises
  repeated event words (`赤壁` twice in `t_002`, the second occurrence is
  targeted), an astral-plane CJK name (`𠀋操`), inherited/unknown time and
  a Claim-less but source-supported person (`周瑜`).
- `artifact-accepted.json` — `chronicle.chapter-artifact / 0.2` produced
  by `accept_reading_candidate` (program-resolved spans, unit IDs,
  segments, anchors, fingerprint, producing run).
- `candidate-*.json` — negative contract examples, each rejected by
  `validate_reading_annotations` in the named category:
  - `candidate-missing-unit.json` — a translation block has no unit.
  - `candidate-unknown-ref.json` — a reader ref is not in the bundle.
  - `candidate-inherit-cross-chapter.json` — inherit points outside the
    chapter.
  - `candidate-inherit-cycle.json` — inheritance forms a cycle.
  - `candidate-overlap-span.json` — two translation spans overlap.
  - `candidate-bad-occurrence.json` — the requested occurrence does not
    exist.
  - `candidate-retrospective-as-time.json` — a retrospective span is used
    as the current time basis.
  - `candidate-forged-role.json` — an `event_role` index points at
    another entity's participant.
  - `candidate-canonical-id.json` — the model wrote a canonical ID.

## Public DTOs

Each example validates against `chronicle-reading-v0.1.schema.json` and
mirrors an interface in `apps/chronicle/webapp/src/lib/reading-types.ts`:

- `reading-locator-example.json` — `ReadingLocator`.
- `reading-unit-example.json` — `ReadingUnit` with program-sliced
  segments; concatenating segment text reproduces the translation block.
- `stream-page-example.json` — `StreamPage` bidirectional envelope.
- `time-group-example.json` — `TimeGroup` narrative-axis section.
- `event-preview-example.json` — `EventPreview` fixed-snapshot preview.
- `event-target-page-example.json` — `EventTargetPage` current/mention
  separated.

`candidate-valid.json` / `artifact-accepted.json` were generated from the
request by the pure contract module; regenerate only through
`reading_contract.accept_reading_candidate` so hashes stay honest.
