# Chronicle ingestion control plane (C1-T1)

The control plane treats one complete historical document as a durable,
restart-safe ingestion workflow. It is **Chronicle application-owned product
persistence** behind `CHRONICLE_DATABASE_URL` (Architecture Amendment 0006)
and must not redefine Loom Runtime Scheduler/Work authority or Loom Storage
semantics.

## Data model

```text
documents (1) ──< document_revisions (N, immutable, supersession chain)
                        │
                        │ revision_id
                        ▼
                  ingestion_jobs (N, one workflow per revision)
                   ├── ingestion_job_stages (8 rows: pipeline vocabulary)
                   ├── ingestion_sections (N ordered scopes)
                   ├── ingestion_chunks (N processing units)
                   │        └── ingestion_chunk_runs (append-only attempts)
                   ├── review_items (human gates)
                   └── ingestion_outputs (assembled artifacts)
```

| Table | Role |
| --- | --- |
| `documents` | Container grouping revisions of one complete source document. |
| `document_revisions` | Immutable uploaded source snapshot (`source_sha256`, `source_bytes`, `source_media_type`). `supersedes_revision_id` links the chain; the tip (`max(revision_no)`) is current. A database trigger rejects every `UPDATE`/`DELETE`. |
| `ingestion_jobs` | One restart-safe workflow per revision: status, attempt counters, nullable worker lease (`lease_owner`, `lease_expires_at`), `checkpoint` JSONB, `error`. |
| `ingestion_job_stages` | One row per pipeline stage per job with its own status/attempt/checkpoint. |
| `ingestion_sections` | Ordered processing scopes of a job (`section_index`, source offsets). Coordinates, not identity. |
| `ingestion_chunks` | Processing units addressed by stable job/section coordinates plus source offsets and hashes. Never historical identity/truth boundaries. |
| `ingestion_chunk_runs` | Append-only per-attempt execution history. Retries insert a new run row; runs are never mutated. |
| `review_items` | Human gates (`chunk_failure`, `stage_gate`, `quality_flag`; `open`/`resolved`/`dismissed`). |
| `ingestion_outputs` | Assembled artifacts bound to exactly one `(job_id, revision_id)`. Downstream C0 staged/resolution/canonical imports remain the historical-knowledge path. |

## Frozen vocabularies

Job statuses: `queued`, `running`, `needs_review`, `failed`, `cancelled`, `completed`.
`failed`, `cancelled`, and `completed` are terminal.

Stage vocabulary: `prepare`, `structure`, `segment`, `extract`, `assemble`,
`resolve`, `publish`, `present`.

Stage statuses: `pending`, `running`, `needs_review`, `failed`, `skipped`, `completed`.

Legal transitions (normative: `apps/chronicle/control_plane/src/lib.rs`):

```text
job:   queued -> running|cancelled
       running -> needs_review|failed|cancelled|completed
       needs_review -> running|failed|cancelled
stage: pending -> running|skipped
       running -> needs_review|failed|completed|skipped
       needs_review -> running|failed|skipped
       failed -> running            (retry)
chunk: pending -> running
       running -> needs_review|failed|completed
       needs_review -> running|failed
       failed -> running            (retry)
```

Self-transitions (re-writing the same status, e.g. worker re-entry after a
restart) are accepted as idempotent. Review items resolve exactly once
(`open` -> `resolved`/`dismissed`) and stay auditable.

## Durability rules

- Replacing a source inserts a new revision; old rows are never mutated
  (trigger-enforced) and stay queryable for audit.
- Jobs are claimed under an expiring worker lease (`claim_job`,
  `heartbeat_job`). An expired lease may be taken over after worker loss;
  checkpoints written before the crash survive because they live in
  PostgreSQL, not in worker memory.
- Chunk retries append `ingestion_chunk_runs` rows with monotonically
  increasing `attempt`; run history is never rewritten.
- `trace_provenance` proves every chunk/run/review/output of a job resolves
  to exactly one immutable revision.
- Relationship invariants hold at both layers: the store rejects
  output↔foreign-revision, chunk↔foreign-section, and review↔foreign-chunk
  bindings with `PersistenceConflict`, and database triggers reject the same
  cross-job bindings for any writer bypassing the store.
- Output retries are idempotent: repeating an identical `record_output` call
  returns the already-persisted row's ID, so callers never hold a phantom ID.

## Ownership boundaries

### Rust control plane vs Python model pipeline

- `apps/chronicle/control_plane/` (Rust, zero dependencies, standalone
  workspace) owns the **lifecycle contract**: status vocabularies, legal
  transitions, supersession numbering, and the deterministic in-memory fake
  lifecycle test. It has no SQL and no DB driver by construction.
- `apps/chronicle/persistence/control_plane.py` (Python) owns the
  **PostgreSQL persistence boundary**: it enforces the same transitions at
  the worker-facing store layer because C1 workers are Python. On any
  disagreement, the Rust contract wins.
- `apps/chronicle/ingestion/` (Python prototype/model pipeline) owns
  extraction semantics, segmentation quality, and model calls. It consumes
  chunk coordinates from the control plane and returns outputs to it; it
  never defines job/stage/chunk lifecycle semantics of its own.

### Loom authority boundary

This control plane creates **no new Loom authority path**:

- No Loom Runtime/World/Timeline/Work/Binding tables are read or written.
- No `loom-storage`, `PgStorage`, or `LOOM_DATABASE_URL` dependency exists
  anywhere under `apps/chronicle/` (machine-enforced by
  `tools/check_storage_sql_ownership.py`).
- No `loom-core`/`loom-protocol`/`loom-api`/`loom-runtime` Rust dependency
  exists in the control-plane crate (standalone workspace, zero deps).
- Existing C0 staged/resolution/canonical publication remains the
  historical-knowledge path after ingestion outputs are assembled.
- If a future ingestion need requires changing Loom Core/Runtime/Storage
  semantic authority, stop and raise an Architecture Amendment (C1-T1 stop
  condition).

## Verification

```bash
# Rust contract (tests, clippy, fmt)
cargo test --offline
cargo clippy --offline --all-targets -- -D warnings
cargo fmt --check
# executed inside apps/chronicle/control_plane/

# PostgreSQL 18 control-plane + C0 persistence contracts
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_*.py' -v
```
