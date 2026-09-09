# Chronicle source assembly and within-book resolution (C1-T7)

> 本页保留 C1 组装基线；C2-R1-T07 章级组装见下文“Chapter assembly”一节。本轮章级输入、统一ref映射及来源内候选的目标契约见 [chapter-production.md](chapter-production.md)。

Deterministic assembly of many validated chunk outputs from one
immutable document revision into one revision-scoped source-owned
staged bundle, with conservative within-document Entity/Event linking.
Pure request/validation/merge logic lives in
`apps/chronicle/persistence/assembly.py` (no database, model, or
network); the durable worker path lives in
`apps/chronicle/worker/ingestion_worker.py` (`assemble` stage) on the
C1-T1 control-plane tables behind `CHRONICLE_DATABASE_URL`.

```text
accepted chunk outputs (candidate + locator + run attempt, one revision)
        │
        ▼
assemble_revision → remap temp IDs → merge source → suppress duplicates
        │           → within-book links → report
        ▼
ingestion_outputs row (assembled-source-bundle: bundle + links + report)
+ assemble stage checkpoint (counts, hashes, versions)
```

## Key contracts

- **C0 contract reused, not replaced.** The assembled bundle satisfies
  the same staged Source/Entity/Event/Claim shape (`contract-v0.2`)
  and the same JSON Schema, validated fail-closed inside
  `assemble_revision`. No chunk assigns canonical identity, and neither
  does assembly: a candidate carrying `id` fails the whole assembly,
  and every assembled record keeps a `temp_id`.
- **Revision-scoped IDs.** Chunk-local temp IDs (`ent_001` in chunk 0
  vs `ent_001` in chunk 1) are remapped to `ent_000001`-style IDs so
  independent chunk namespaces can never collide. All references
  (claim subject/object, event participants/places/parent, evidence
  source links) are rewritten through the same mapping.
- **One source, preserved locators.** Per-chunk sources merge into one
  revision-scoped `src_001` (document title wins when present). Claim
  evidence locators keep the C0 shape unchanged; the originating
  chunk/run/revision coordinates travel in the report's per-record
  provenance map, so every record traces end to end.
- **Boundary duplicates suppressed with evidence.** The same assertion
  extracted on both sides of one chunk boundary (identical predicate,
  evidence text, subject/object surfaces for claims; identical type,
  title, time, participant/place surfaces for events) keeps the first
  and suppresses the later duplicate only when the chunk locators
  verify the overlap: intersecting source spans or declared boundary
  overlap characters. Adjacent non-overlapping repeats and distant
  repetitions survive as distinct occurrences and are recorded as
  preserved repeats. Every suppression is recorded with its
  signature; nothing is silently multiplied or silently dropped.
- **Conservative within-book links.** Entity pairs across chunks need
  the same type plus a shared exact stable surface, but a shared name
  alone never proves identity: same-name records stay `uncertain`
  unless stronger source-bounded evidence exists — a second shared
  stable surface beyond the name, or co-reference proven by a
  suppressed boundary duplicate both records participated in.
  Same-name occurrences across types stay distinct with an
  `ambiguous_same_name` warning. Event pairs need compatible time
  plus participant (and, for broad types, place) overlap;
  non-duplicate pairs stay `uncertain` for C1-T8 review. Linking
  never merges records and never assigns canonical IDs.
- **Deterministic.** No timestamps, UUIDs, or randomness appear in the
  artifact. Unchanged accepted chunk outputs produce byte-identical
  canonical JSON (unit-tested).
- **Fail closed.** Empty input, duplicate chunk indexes, mixed
  revisions, canonical IDs, or a missing accepted chunk output raise
  instead of producing a partial bundle. The worker maps this to a
  failed assemble stage with no output row.
- **Restart-safe.** The output is content-addressed
  (`job, artifact_type, artifact_sha256`), so a resumed worker reruns
  the stage as a no-op. Completed chunks are the only assembly input;
  assembly itself never calls the model.
- **ContextState is never authority.** The assembled artifact carries
  `authoritative: false` beside the bundle, mirroring the C1-T6 chunk
  checkpoints it consumes.

## Production hook

The deployed worker runs real assembly at the `assemble` stage
whenever real extraction ran (`chunk_model` plus `revision_source`
set); otherwise the stage keeps the deterministic fake executor.
No additional configuration is needed.

## Chapter assembly (C2-R1-T07)

`assemble_chapters(accepted_artifacts, chapter_plan)` in
`apps/chronicle/persistence/assembly.py` is the chapter-path entry point
(chapter-production.md §5). It consumes only T01 accepted artifacts
(`chronicle.chapter-artifact / 0.1`) plus the T03 chapter plan
(`c2r1-chapters-v1`); it never calls the model, never mutates the source
candidate, and never touches the worker.

```text
accepted chapter artifacts (one per planned chapter, one revision)
+ chapter plan (expected chapter set, revision triple)
        │
        ▼
assemble_chapters → verify full chapter coverage → remap (chapter_index, local_ref)
        │             → rewrite C0 + translation/mentions/record_sources → single src_001
        ▼
assembled-source-bundle (bundle + translation_blocks + mentions + record_sources + anchors + report)
```

Key contracts:

- **Full coverage, stable order.** Every planned chapter must have
  exactly one accepted artifact with a matching revision/source/plan and
  model contract version, sorted by `chapter_index`. Missing, extra,
  duplicate, mixed-revision, or unaccepted/tampered products fail
  closed; a finished subset can never pass as the whole book.
- **One mapping for every ref.** `(chapter_index, local temp_id)` maps
  to revision refs reusing the original namespace rule (`ent_001` in
  chapter 0 → `ent_000001`, in chapter 1 → `ent_001001`). C0 claim/event
  fields, translation `entity_refs`/`event_refs`, mention
  `target_ref`/`candidate_refs`, and `record_sources` all use that same
  mapping. Translation blocks without a Claim are preserved. Claim
  `subject`/`object` kinds are normalized at the output boundary from
  the chapter-candidate vocabulary (`entity`/`event`) to the C0 bundle
  vocabulary (`entity_ref`/`event_ref`); `literal`/`null` objects are
  preserved verbatim.
- **One revision, one source.** All chapters merge into a single
  `src_001`; per-record `chapter_by_ref` (`revision_ref → chapter_id`)  plus exact artifact provenance (`artifact_sha256`,
  `candidate_sha256`, `request_fingerprint`) serve T08 candidacy and T10
  evidence lookup. Anchors keep their chapter binding; a cross-chapter
  anchor fails closed.
- **No automatic merging.** Unlike the chunk path, chapter assembly
  performs no boundary-duplicate suppression and emits no same-links.
  Different chapters may describe the same occurrence, but this stage
  keeps them as distinct pending records and never merges by name.
  Same-name cross-chapter records stay independent; the source count
  does not inflate per chapter.
- **Deterministic, fail-closed report.** The report carries the chapter
  manifest, `chapter_by_ref`, `local_to_revision` (`"(index,local)" →
  revision_ref`), per-chapter artifact hashes, input counts, and
  `bundle_sha256`. Unchanged inputs yield byte-identical canonical JSON
  regardless of input order (unit-tested).

Verification:

```bash
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_assembly_unit.py' -v
```
