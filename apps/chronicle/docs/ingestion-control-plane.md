# Chronicle C1 ingestion control plane (C1-T1 / #490)

The minimum Chronicle-owned contract needed to treat a complete historical
document as a durable, restart-safe ingestion workflow. This document is the
durable design record; the executable contract lives in three places that
must be changed together:

- `../persistence/migrations/0002_chronicle_c1_control_plane.sql` —
  `PostgreSQL` vocabularies (`CHECK`), immutability triggers, indexes;
- `../persistence/control_plane_store.py` — transition guards, worker
  leases (`SELECT ... FOR UPDATE SKIP LOCKED`), checkpoints, provenance;
- `../control_plane/` — standalone Rust domain crate: frozen status types,
  transition graph, deterministic in-memory lifecycle fake.

## Data model

```text
documents (1) ──< document_revisions (immutable, N, supersession chain)
      │
      └─< ingestion_jobs (bound to exactly ONE revision)
              ├── ingestion_job_stages (8-row pipeline state)
              ├── ingestion_sections (source ranges of the revision)
              │       └── ingestion_chunks (processing units)
              │               └── ingestion_chunk_runs (append-only attempts)
              ├── review_items (operator decision gates)
              └── ingestion_outputs (assembled artifacts -> C0 path)
```

Every row produced by a job traces back to one immutable revision through
`job -> revision_id`, or `chunk/run/review/output -> job_id -> revision_id`
(`job_provenance()` in the store, `FakeControlPlane::provenance` in Rust).

## Frozen vocabularies

Job statuses: `queued`, `running`, `needs_review`, `failed`, `cancelled`,
`completed`.

Pipeline stages (execution order): `prepare`, `structure`, `segment`,
`extract`, `assemble`, `resolve`, `publish`, `present`.

Stage statuses: `pending`, `running`, `needs_review`, `failed`, `skipped`,
`completed`.

Chunk statuses: `pending`, `processing`, `needs_review`, `failed`,
`completed`. Run statuses: `started`, `succeeded`, `failed`. Review
statuses: `open`, `approved`, `rejected`, `superseded`.

## Legal transitions

```text
job:   queued -> running | cancelled
       running -> needs_review | failed | cancelled | completed
       needs_review -> running | failed | cancelled | completed
       failed -> running (resume/retry) | cancelled
       cancelled / completed are terminal

stage: pending -> running | skipped
       running -> needs_review | failed | skipped | completed
       needs_review -> running | failed | skipped | completed
       failed -> running | skipped
       skipped -> running (re-run)
       completed is terminal

chunk: pending -> processing
       processing -> needs_review | failed | completed
       needs_review -> processing | failed | completed
       failed -> processing (retry; the retry is a NEW run)
       completed is terminal

run:   started -> succeeded | failed (exactly once; finished runs immutable)
review: open -> approved | rejected | superseded (exactly once)
```

## Immutable revision / supersession semantics

Replacing a source creates a new revision; it never destructively overwrites
the old uploaded source:

- the first revision of a document is `revision_number = 1` with no
  supersession link;
- a replacement must name `supersedes_revision_id`, which must belong to
  the same document; the new number is exactly previous + 1 (enforced by
  the `document_revisions_supersession_trg` trigger as well as the store);
- the same source bytes cannot be ingested twice for one document
  (`UNIQUE (document_id, source_sha256)`);
- `UPDATE`/`DELETE` on `document_revisions` is rejected by the database
  trigger. Deleting already-published historical facts as part of source
  replacement is explicitly out of scope: old revisions stay queryable, and
  downstream C0 canonical rows are never rewritten by supersession.

Chunk runs and ingestion outputs are likewise append-only: a started run
completes exactly once (trigger-enforced), retries insert new runs, and a
corrected output is a new row.

## Chunk identity

A chunk is identified by the stable `(job_id, section_id, chunk_index)`
coordinate plus the `(source_start_offset, source_end_offset,
source_sha256)` location of the revision bytes it covers. Chunks are
model-processing units, not historical identity authority: they never
define who/what an Entity or Event is. Historical identity stays with the
C0 staged -> resolution -> canonical path that assembled ingestion outputs
feed into.

## Worker lease / checkpoint / retry (provider-neutral)

- `claim_job` assigns `worker_id`, `lease_expires_at`, `heartbeat_at` and
  bumps `attempt_count` under `SELECT ... FOR UPDATE SKIP LOCKED`, so
  concurrent workers never claim the same job.
- A running job whose lease expired (crashed worker) becomes claimable
  again with its `checkpoint` JSONB intact: restart recovery without a
  provider-specific supervisor.
- `heartbeat_job` renews liveness; heartbeats from a worker that lost the
  lease are rejected. `save_job_checkpoint` records progress without a
  status change.
- `max_attempts` (jobs) and `max_retries` (chunks) bound automatic recovery;
  resuming a `failed` job is an explicit operator transition, not a silent
  side effect.

No provider-specific worker implementation is frozen: the contract only
requires a worker identity string, a lease deadline, heartbeats, and
checkpoints. The C1-T4 durable worker will implement this contract against
`PostgreSQL`.

## C0 preservation

Migration `0002` only creates new tables, indexes, functions, and triggers.
It does not `ALTER`, rewrite, or drop any `0001` staged / resolution /
canonical table. `test_control_plane_postgres.py::test_c0_tables_preserved_and_writable`
asserts every C0 table still exists and still accepts writes after `0002`.

## Ownership boundary

```text
Loom engine domain (untouched)
  Runtime Scheduler / Work authority, World/Timeline storage, loom-storage,
  LOOM_DATABASE_URL — none of these are referenced, imported, or migrated
  here. No new Loom authority path is introduced.

Chronicle Rust control plane (apps/chronicle/control_plane)
  Owns the durable orchestration CONTRACT: status vocabularies, legal
  transitions, supersession numbering, lease/checkpoint shapes. Zero
  dependencies (std only); deliberately detached from the Loom Cargo
  workspace so architecture governance never classifies it as a Loom
  framework crate. It performs no I/O and holds no database handle.

Chronicle Python persistence (apps/chronicle/persistence)
  Owns the DURABLE MECHANISM behind CHRONICLE_DATABASE_URL: migrations,
  stores, leases, and the PG18 integration tests. It never consumes
  LOOM_DATABASE_URL.

Experimental Python model pipeline (ingestion/, C1-T5/T-6 scope)
  Owns segmentation and extraction SEMANTICS (what the stages compute).
  It runs inside the orchestration contract defined here but does not
  redefine it.
```

If future work needs the control plane to mutate Loom Runtime/World/
Timeline semantics instead of Chronicle-owned rows, that is an
Architecture Amendment (stop condition of #490), not an implementation
detail.

## Verification

```bash
# Rust domain + deterministic fake lifecycle (workspace-local target dir)
cargo test --target-dir ./target \
  --manifest-path apps/chronicle/control_plane/Cargo.toml
cargo clippy --target-dir ./target \
  --manifest-path apps/chronicle/control_plane/Cargo.toml --all-targets

# Chronicle PostgreSQL contracts incl. C0 regressions (needs PG18 service;
# reuses tools/postgres-test.sh when LOOM_TEST_POSTGRES_URL is unset)
python3 -m pip install -r apps/chronicle/persistence/requirements.txt
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_*.py' -v

# Architecture / storage-ownership governance
python3 tools/check_architecture.py
python3 tools/check_storage_sql_ownership.py
```
