# Chronicle structure, segmentation, and context state (C1-T5)

Deterministic, versioned preparation of one immutable document revision for
model processing. Pure text computation lives in
`apps/chronicle/persistence/segmentation.py` (no database, model, or
network); the durable worker path lives in
`apps/chronicle/worker/ingestion_worker.py` (`structure`/`segment` stages)
on the C1-T1 control-plane tables behind `CHRONICLE_DATABASE_URL`.

## What it produces

```text
normalized revision text (documents.decode_source)
        │
        ▼
detect_structure → sections (volume/chapter/biography/heading/…)
        │
        ▼
segment_revision → chunk plans + manifest (plan_sha256)
        │
        ▼
context_chain → per-chunk {input, output} ContextState + budget gates
        │
        ▼
ensure_sections / ensure_chunks → ingestion_sections / ingestion_chunks
        + stage checkpoints (structure/segment) and per-chunk checkpoints
```

## Key contracts

- **Offsets are character offsets into the normalized revision text**
  (`offset_unit: "chars-normalized-utf8"`). `text[start:end]` reconstructs
  the exact chunk; `content_sha256` proves it. The full source is never
  duplicated per chunk — only offsets, hashes, and bounded boundary
  strings are persisted.
- **Natural boundaries win.** Headings open sections; paragraphs, then
  lines, then sentence punctuation bound chunk size. A hard cut is only
  the fallback for a unit that exceeds `max_chunk_chars` on its own.
  Overlap defaults to zero duplicated characters; continuity travels in
  `ContextState` instead of RAG-style heavy overlap.
- **ContextState is versioned (`c1t5-ctx-v1`) and auditable**: inherited
  historical time (verbatim, `explicit` vs `inherited` scope, origin
  chunk), active entity/place surfaces, recent event sentences, explicitly
  uncertain coreference hints, and bounded previous/next boundary context.
  Chunk N+1's input equals chunk N's output.
- **Nothing here is historical authority.** Every chunk checkpoint and
  manifest carries `authoritative: false`. Inherited time never gains
  invented precision; a revision with no time expressions yields an empty
  list, not a guess. Coreference hints are `uncertain: true` surface
  links for C1-T6 extraction, never resolution decisions.
- **Reproducibility.** Segmentation is a pure function of
  `(text, source_sha256, config, versions)`; `plan_sha256` in the manifest
  and both stage checkpoints proves unchanged input plus the same
  `c1t5-v1` segmentation version reproduces identical records.
- **Budgets fail closed.** `SegmentationConfig` reserves prompt, context,
  and output space inside `max_input_chars`; an oversized chunk plus
  serialized context raises instead of silently overflowing. No model is
  called in C1-T5 (`model_version: none-deterministic-v1`); the version
  slots exist so C1-T6 fills them without a schema change.
- **Restart-safe.** Section/chunk writes are idempotent on
  `(job, index)`; re-entry reuses rows, locator drift fails closed with
  `PersistenceConflict`, and completed stages are never re-run. Jobs
  without a revision source keep the exact C1-T4 fake path.

## Deterministic fallback

A document with no detectable headings becomes one `document`-kind
section (`fallback: "single-section"` in the manifest). Structure
detection is a conservative line-anchored pattern set
(`STRUCTURE_VERSION`); prose lines never open sections.

## Continuity fixture

`apps/chronicle/ingestion/fixtures/c1t5-boundary-continuity/` (`raw.txt`
plus `expected-context.json`) proves pronouns, inherited regnal time, and
event sentences survive a chunk boundary. The unit suite
(`persistence/test_segmentation_unit.py`) and the PostgreSQL resume suite
(`worker/test_segmentation_postgres.py`) consume it.
