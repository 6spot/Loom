# Chronicle source assembly and within-book resolution (C1-T7)

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
