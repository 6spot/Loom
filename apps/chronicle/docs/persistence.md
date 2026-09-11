# Chronicle PostgreSQL persistence

Chronicle persistence is application-owned infrastructure for accepted Chronicle ingestion artifacts. It stores source-owned staged records, cross-source Resolution Links, and deterministic canonical publication output as three separately auditable layers.

It is **not** a Loom Storage adapter and it must not read or mutate Loom Runtime/Storage tables. Product features continue to use Loom through its public surfaces where Loom-owned authority is involved.

## Connection boundary

Production/development persistence uses a Chronicle-owned PostgreSQL connection:

```text
CHRONICLE_DATABASE_URL
```

Use a separate Chronicle database when practical, even when Loom and Chronicle share the same PostgreSQL 18 server. A typical layout is:

```text
PostgreSQL 18 server
├── loom_control   # Loom-owned persistence
└── chronicle      # Chronicle application persistence
    └── schema chronicle
```

The C0-T9 adapter never consumes `LOOM_DATABASE_URL` as an application contract.

## PostgreSQL baseline

C0-T9 targets the repository-supported PostgreSQL 18 family. The existing `pgvector/pgvector:0.8.6-pg18` image is suitable, but this task does not create vector columns, embeddings, or search indexes.

PostgreSQL 18 UUID inspection is used to enforce that persisted canonical IDs are UUIDv7. Chronicle still receives those IDs from C0-T8 publication; the database does not generate replacement canonical identity.

## Schema ownership

Migrations live only under:

```text
apps/chronicle/persistence/migrations/
```

`chronicle.schema_migrations` records each migration filename and SHA-256 checksum. Reapplying the same migration/checksum is a no-op. Reusing a migration filename with different SQL is a persistence conflict and fails rather than silently changing schema history.

The first migration stores:

- source bundle metadata and the complete staged bundle payload;
- individual staged Entity/Event/Claim rows and warnings;
- complete Resolution Link artifacts plus Entity/Event decisions and warnings;
- complete canonical catalog artifacts;
- CanonicalEntity/CanonicalEvent UUIDs;
- source representation membership;
- canonical `related_occurrence` relations;
- the exact persisted Resolution artifact(s) supporting each relation;
- import-set metadata for replay/idempotency.

JSONB copies preserve the accepted artifact content while relational keys provide durable identity and queryability for the later C0-T10 read model.

The second migration (`0002_chronicle_c1_control_plane.sql`, C1-T1) adds
the ingestion control plane — Documents, immutable Document Revisions,
Jobs/Stages/Sections/Chunks/Runs, review items, and outputs — without
touching the C0 tables above. The third migration
(`0003_chronicle_c1_documents.sql`, C1-T3) adds per-revision upload
metadata (filename, relative storage key, character count,
language/source labels) plus the `document_current_revisions` tip view.
Uploaded source bytes themselves live on the filesystem under
`CHRONICLE_SOURCE_DIR` (see `documents.md`); the database holds the
auditable metadata and relative keys, never absolute host paths.

## Immutability and idempotency

Persistence never uses an update-on-conflict policy for accepted historical records.

For a stable key:

```text
same key + same canonical JSON content
→ reuse / no-op

same key + different content
→ PersistenceConflict
```

This applies to source bundle labels and staged record refs. Canonical representation membership is similarly immutable: once `(bundle_label, record_ref)` belongs to a canonical UUID, a later import cannot silently assign it to another UUID.

Artifact hashes are SHA-256 over canonical JSON serialization (`sort_keys=True`, compact separators). They are replay/audit identifiers, not historical semantic authority.

## Transaction boundary

One import call writes all supplied staged bundles, Resolution Links, canonical catalog data, and import-set metadata in one PostgreSQL transaction after migrations are applied.

```text
BEGIN
  staged bundles / records
  resolution artifacts / links
  canonical catalog / membership / relations
  import-set metadata
COMMIT
```

Any conflict, foreign-key failure, invalid UUID, or PostgreSQL error rolls back the entire import transaction.

## CLI

Install the Chronicle persistence dependencies in the active Chronicle virtualenv:

```bash
python3 -m pip install -r apps/chronicle/persistence/requirements.txt
```

Then persist accepted artifacts:

```bash
export CHRONICLE_DATABASE_URL='postgresql://USER:PASSWORD@HOST:5432/chronicle'

python3 apps/chronicle/persistence/chronicle_persist.py \
  --bundle wudi=apps/chronicle/.artifacts/c0-t7/wudi/final.json \
  --bundle wuzhu=apps/chronicle/.artifacts/c0-t7/wuzhu/final.json \
  --resolution apps/chronicle/.artifacts/c0-t7/resolution/links.json \
  --catalog apps/chronicle/.artifacts/c0-t7/publication/catalog.json \
  --report apps/chronicle/.artifacts/c0-t9/persistence/report.json
```

The CLI validates all supplied JSON against the already accepted staged, resolution, and canonical schemas before opening the persistence write path.

A successful first import prints a summary beginning with:

```text
chronicle persistence: PASS import_created=true
```

Repeating the identical command should print `import_created=false` and preserve the same canonical UUID rows.

## PostgreSQL 18 integration tests

The integration test reuses the repository's documented PostgreSQL control service only to create a unique temporary Chronicle database for each test. It does not create Chronicle tables inside Loom's control schema.

```bash
python3 -m pip install -r apps/chronicle/persistence/requirements.txt
python3 -m unittest apps/chronicle/persistence/test_postgres_v0.py -v
```

When `LOOM_TEST_POSTGRES_URL` is unset, the test follows the repository-local default `postgresql://loom:loom@127.0.0.1:15432/loom_control` and starts/reuses `tools/postgres-test.sh up` if needed. An explicit `LOOM_TEST_POSTGRES_URL` is used as-is and does not fall back elsewhere.

The test suite covers migration checksum drift, import idempotency, restart/reconnect identity stability, exact Claim evidence retrieval, transaction rollback on immutable bundle conflicts, and transaction rollback on canonical membership reassignment.

## Backup and replay ownership

A PostgreSQL backup of the Chronicle database is an operational backup of the application-owned persistence layer. It does not replace source provenance or convert database rows into Loom-owned semantic authority.

Two recovery paths are valid:

1. restore a Chronicle database backup; or
2. provision an empty Chronicle database, apply the checked-in migrations, and replay the accepted staged/resolution/canonical artifacts through `chronicle_persist.py`.

Because accepted payloads and canonical UUIDs are persisted rather than regenerated, restart/restore does not ask a model to resolve identity again.

Do not restore Chronicle tables into Loom-owned schemas, and do not use Loom database backup/repair procedures as Chronicle application migrations.

## Chapter artifacts and publications (C2-R1-T04)

The sixth migration (`0006_chronicle_chapters.sql`, owned by C2-R1-T04)
adds the chapter layer from `chapter-production.md` sections 5/7 without
touching Loom authority or the 0005 Reader Presentation Claim-only
support constraint:

- `chronicle.chapter_artifacts` — one immutable accepted joint product
  per `(job_id, chapter_id)`: `artifact_sha256` PK, job/revision/
  document/chapter/chunk/producing-run bindings, `request_fingerprint`,
  `candidate_sha256`, and the full `chronicle.chapter-artifact / 0.1`
  payload. The complete product (translation + extraction +
  record_sources) is accepted only through the chapter-store write
  entry; partial products are never persisted. Binding triggers reject
  cross-job revision/chunk/run references at the database (D-1 style),
  independent of worker code.
- `chronicle.chapter_publications` — one immutable public reading
  version per chapter: UUIDv7 `publication_id` PK, `artifact_sha256`,
  `catalog_sha256`, `assembled_bundle_sha256`, job/revision/document/
  chapter bindings, publication payload, and `published_at`. The same
  `(artifact, catalog, assembled-bundle)` triple with identical bytes is
  idempotent; the same triple with different bytes is a conflict.
- `chronicle.resolution_artifacts.scope` plus the
  `resolution_artifacts_bundle_scope_valid` envelope: same-bundle
  artifacts are allowed only for `chronicle.resolution-links / 0.2`
  with `scope = 'within_revision'`. v0.1 and `cross_source` keep the
  original distinct-bundle requirement; foreign keys and decision enums
  are unchanged. Whether a same-bundle candidate spans different
  chapters is validated by T08, not here.
- `resolution_entity_links` / `resolution_event_links` gain
  `*_no_self_ref` checks: the two ends `(bundle, ref)` of one link must
  differ.
- `chronicle.canonical_catalogs.publication_sequence` — unique
  increasing identity column, structure only. The unified advisory lock,
  the locked write path, and the latest-catalog read migration off
  `imported_at` belong to T13, which must reuse this column.

`apps/chronicle/persistence/chapter_store.py` holds the new chapter
tables; catalogs stay owned by `canonical_store.py`. All mutating
entries take the caller-owned connection plus `(job_id, worker)` and
fence on the job lease inside one short transaction (model waits never
hold a transaction):

- `record_accepted_chapter_fenced(conn, *, job_id, chunk_id, worker,
  request, candidate, producing_run)` — re-validates the exact
  request/candidate pair through the T01 contract, checks
  job/revision/chunk/producing-run/fingerprint consistency, then commits
  the artifact row, the chunk accepted pointer
  (`checkpoint.accepted_chapter_artifact`), and the chunk `completed`
  status atomically. A committed producing run is adopted via full
  re-validation, never re-executed. Cancelled/failed/completed jobs and
  lost leases (`LeaseLost`) cannot write.
- `read_accepted_chapters` / `read_accepted_chapter` — read-only resume
  path: an interrupted worker reads the accepted complete results
  without creating another chapter queue/run.
- `persist_chapter_publication(conn, *, job_id, worker,
  artifact_sha256, catalog_sha256, assembled_bundle_sha256,
  publication)` — records one public reading version (no worker wiring;
  the atomic multi-chapter publish belongs to T13).
- `list_published_chapters` / `read_published_chapter` — public
  visibility gate: only published chapters appear; accepted-but-
  unpublished chapters stay invisible.

```bash
python3 -m pip install -r apps/chronicle/persistence/requirements.txt
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_chapter_store_postgres.py' -v
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_control_plane_postgres.py' -v
python3 tools/check_storage_sql_ownership.py
```

When `LOOM_TEST_POSTGRES_URL` is unset, the tests follow the
repository-local default `postgresql://loom:loom@127.0.0.1:15432/loom_control`
and start/reuse `tools/postgres-test.sh up` if needed.

## Continuous-reading streams (C2-R2-T05)

The seventh migration (`0007_chronicle_reading_streams.sql`, owned by
C2-R2-T05) adds the immutable reading index from
`continuous-reading.md` sections 4/5 without touching any first-round table,
without copying translation text, source anchors, entity tables or model
runs, and without relaxing the 0006 chapter guards:

- `chronicle.reading_streams` — UUIDv7 `stream_id`, unique `revision_id`,
  `origin_catalog_sha`, `manifest_sha`, the `content_sha256` digest of the
  complete normalized compiled input, the ordered `chapter_publication_ids`,
  unit/group counts and the immutable `manifest`. One revision has exactly one
  stream.
- `chronicle.reading_units` — `(stream_id, ordinal)` primary key, globally
  unique `unit_id`, `publication_id`/`artifact_sha256`/`chapter_id`/`block_id`,
  `text_hash`, the compiled `narrative_time`/`segments`/`context_entities`
  and `source_anchor_ids`. The body text is never duplicated: it stays in the
  referenced first-round `chapter_publications` row.
- `chronicle.reading_time_groups` — `(stream_id, ordinal)` primary key,
  unique `group_id`, first/last unit ordinal and the precompiled display
  fields. Pagination reuses the fixed `group_id`; it never rebuilds a title.
- `chronicle.reading_event_occurrences` — `stream_id`/`unit_ordinal`,
  `event_kind` (`span` or `current`), `span_id`, `canonical_event_id`,
  `relation` and the source `(bundle_label, record_ref)`. It is the exact
  reverse index for "which published positions talk about this event".

All four tables are append-only (mutation triggers) and enforce their
references at the database: the stream trigger proves every
`chapter_publication_ids` element exists, is unique, belongs to the stream's
own revision/document and was published under the stream's `origin_catalog_sha`
(a publication from a later catalog can never enter an older snapshot); the
unit trigger proves the publication is part of the stream and its
artifact/chapter match; the group trigger proves first/last units exist and the
covered units share one `group_id`; the occurrence trigger proves the source
representation is listed by the stream's origin catalog payload.

`apps/chronicle/persistence/reading_store.py` owns the tables:

- `persist_reading_stream(conn, stream)` — writes the stream, units, groups
  and occurrences **inside the caller's already-open transaction**. It never
  opens or commits a transaction and never takes a second worker lease, so
  T06's unique publish transaction can commit the catalog, every chapter
  publication and the whole reading index atomically. The accepted compiled
  stream is a plain JSON object with `revision_id`, `document_id`,
  `origin_catalog_sha`, `manifest`, `chapter_publication_ids`, ordered
  `units`, ordered `groups` and `event_occurrences`. The T04 compiler is its
  producer. Replay is idempotent only when the **complete** normalized input
  matches the stored `content_sha256`: changing any unit, group, occurrence or
  publication binding — even while keeping the manifest bytes — raises
  `PersistenceConflict` (`immutable_stream_conflict`).
- `read_reading_stream` / `list_reading_streams` / `read_reading_unit` /
  `read_reading_units` / `read_reading_groups` / `read_event_occurrences` —
  SELECT-only, bounded helpers. Ordinal and group pages use indexed keyset
  ranges with `limit + 1`; event reverse lookup uses the
  `reading_event_occurrences_event_idx` index. No helper reads the whole body
  corpus and slices it in Python. Every helper accepts an optional snapshot
  catalog and then enforces the same visibility guard, so an exact unit read
  cannot leak a later stream through an older snapshot.

Snapshot visibility never uses wall-clock time. A stream is in range for a
snapshot when its origin catalog's `publication_sequence` is `<=` the
snapshot's; event occurrences are additionally restricted to the exact
`(canonical_id, bundle, ref)` members of the snapshot catalog **payload**, so
an old snapshot never sees a later representation or stream even for the same
canonical id. The global representation tables are never consulted on a read.

```bash
python3 -m pip install -r apps/chronicle/persistence/requirements.txt
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_reading_store_postgres.py' -v
python3 tools/check_storage_sql_ownership.py
```

When `LOOM_TEST_POSTGRES_URL` is unset, the reading-store test follows the
same repository-local control database and `tools/postgres-test.sh up`
fallback as the other persistence suites. Its fixture seeds two sources,
multiple revisions and multiple catalogs; that is an explicit test loading
path, not a second production success path.

The worker/publication wiring and the chapter completeness gate belong to
T06; the stream/event read APIs belong to T07/T08. Both reuse these helpers
instead of building a second read or write path.

## Boundary to C0-T10

C0-T10 may read these Chronicle-owned tables through a Chronicle repository/read-model module. It must preserve the same three-layer distinction when assembling Timeline, Event Detail, and Entity Detail responses. C0-T10 must not turn persistence rows into synthetic historical truth or collapse unresolved Resolution decisions.
