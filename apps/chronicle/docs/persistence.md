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

## Boundary to C0-T10

C0-T10 may read these Chronicle-owned tables through a Chronicle repository/read-model module. It must preserve the same three-layer distinction when assembling Timeline, Event Detail, and Entity Detail responses. C0-T10 must not turn persistence rows into synthetic historical truth or collapse unresolved Resolution decisions.
