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
- **Structure is persisted as a hierarchy, not just labels.**
  `ingestion_sections` stores `kind` (volume/chapter/biography/treatise/
  heading/preamble/document, or `unknown` for pre-detection rows), `depth`
  (nesting level), and `parent_section_index` (nearest preceding section
  with a strictly smaller depth, NULL at the top). A restart re-reads the
  hierarchy from the section rows in `section_index` order, and resume
  validates kind/depth/parent against the deterministic plan instead of
  trusting them.
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
  and output space inside `max_input_chars`; the accounted total holds
  every reserve plus the actual serialized context and chunk, so an
  oversized combination raises instead of silently overflowing. No model is
  called in C1-T5 (`model_version: none-deterministic-v1`); the version
  slots exist so C1-T6 fills them without a schema change.
- **Restart-safe.** Section/chunk writes are idempotent on
  `(job, index)`; re-entry reuses rows, locator/source drift fails closed
  with `PersistenceConflict`, the complete persisted section/chunk set must
  equal the plan set (stale extra rows fail instead of lingering for a
  later extract), and completed stages are never re-run. Chunk rows store
  the whole-revision `source_sha256` separately from the slice
  `content_sha256`, and the worker verifies the loaded bytes against the
  immutable revision row before accepting a plan. Jobs without a revision
  source keep the exact C1-T4 fake path.

## Production source loading

The deployed worker (`compose.chronicle.yaml: chronicle-worker`, `worker`
profile) mounts the same Chronicle-owned source volume the upload sidecar
writes and sets `CHRONICLE_SOURCE_DIR`, so `structure`/`segment` stages run
the real versioned segmentation over stored revision bytes
(`build_revision_source`: read revision row → load exact bytes → verify
byte hash against the immutable row → `decode_source`). `--source-dir`
overrides the env. Missing files, hash mismatches, undecodable bytes, and
empty normalizations all fail the job (bounded Studio retry) instead of
silently completing it through fake checkpoints. Without a source
directory every stage keeps the deterministic fake executor.

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
