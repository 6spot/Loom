# Chronicle context-aware chunk extraction (C1-T6)

Deterministic, versioned extraction of one persisted book chunk into
schema-valid Entity/Event/Claim candidates with exact evidence and
replayable model-attempt provenance. Pure request/validation/history
logic lives in `apps/chronicle/persistence/extraction.py` (no database,
model, or network); the durable worker path lives in
`apps/chronicle/worker/ingestion_worker.py` (`extract` stage) on the
C1-T1 control-plane tables behind `CHRONICLE_DATABASE_URL`.

## What it produces

```text
persisted chunk (offsets, section, revision) + ContextState input
        │
        ▼
build_chunk_request → bounded prompt + request metadata
        │
        ▼
extract_chunk → initial attempt → validate → [bounded correction] → accepted | fail-closed
        │
        ▼
build_chunk_run → ChunkRun history (versions, request, attempts, candidate|error)
        │
        ▼
ingestion_chunk_runs rows (one per model attempt, append-only)
+ chunk checkpoint extraction layer (accepted candidate + producing run)
```

## Key contracts

- **C0 contract reused, not replaced.** Candidates satisfy the same
  staged Source/Entity/Event/Claim shape (`contract-v0.2`) and the same
  JSON Schema. No chunk assigns canonical identity: a record carrying
  `id` fails validation instead of being coerced.
- **Exact evidence per chunk.** Every `Claim.evidence.text` must be an
  exact substring of the *current chunk text*. Inherited context and
  boundary strings aid interpretation only and are never evidence.
  Chunk coordinates (offsets/hashes/revision) travel in the run
  envelope; the C0 `evidence.locator` shape is unchanged.
- **Inherited time without invented precision.** An `original_text`
  found in the chunk is explicit; one carried from ContextState must
  list `inherited_fields` verbatim. Normalized month/day always stay
  null; a normalized year is accepted only when document metadata
  supplies the exact verified mapping, otherwise it stays null too.
- **Replayable history.** Each attempt stores prompt, raw response,
  validation report, and candidate verbatim (within char bounds).
  `verify_history` re-parses and re-validates the stored pairs; any
  disagreement fails closed downstream.
- **Bounded repair, fail closed.** At most `1 + max_repair_attempts`
  model calls (default 1 repair, mirroring the C0 repair bound); a
  still-invalid candidate records the failure instead of manufacturing
  a valid-looking result.
- **ContextState is never authority.** It is stored beside the
  candidate under its own key, never merged into it, and every run and
  accepted checkpoint carries `authoritative: false`. Extraction
  confidence (`extraction.confidence`) stays separate from historical
  assessment (claims start `unassessed`).
- **Restart-safe.** Completed chunks are never re-run, so ordinary
  resume never duplicates a successful chunk. A chunk whose accepted
  run row committed but whose accepted layer/status did not (worker
  exit between those commits) is adopted from history with zero new
  model calls. Retries append new `ingestion_chunk_runs` rows; earlier
  attempts are never overwritten.
  The accepted-output layer records the producing run attempt, and the
  C1-T5 segmentation checkpoint is preserved alongside (merged, not
  replaced).
- **Schema bound by default.** The worker real-extract path binds the
  canonical staged-bundle schema (`require_canonical_schema`: `None`
  binds it, any non-canonical dict fails closed), so permissive
  dictionaries cannot accept malformed candidates. `schema=None` in
  the pure function skips only the schema layer for focused unit
  tests, never for production extraction. Schema evolution goes
  through contract versioning, never per-call dictionaries.

## Production model hook

The deployed worker keeps the deterministic fake `extract` path unless
a `chunk_model` provider (`complete(prompt) -> str` plus `name`) is
supplied alongside the C1-T5 `revision_source`. A model without a
revision source fails the job instead of extracting unknown bytes.
Optional `extraction_schema` (full JSON Schema dict) and
`allowed_predicates` tighten validation; `document_meta` supplies
document-level metadata such as a verified normalized year over the
database title.

## Fixture

`apps/chronicle/ingestion/fixtures/c1t6-inherited-jianan/` (`raw.txt`
plus `extraction.json`) segments into paragraph-aligned chunks where
only the opening chunk carries the explicit regnal year 建安十三年;
later chunks inherit it verbatim with the verified normalized year
208 and resolve 其/公-style references against inherited surfaces.
The unit suite (`persistence/test_extraction_unit.py`) and the
PostgreSQL extract suite (`worker/test_extraction_postgres.py`)
consume it.
