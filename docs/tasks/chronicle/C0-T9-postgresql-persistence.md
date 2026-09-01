---
task: C0-T9
issue: 471
status: in_progress
depends_on: [C0-T8]
created_at: 2026-09-01
started_at: 2026-09-01
completed_at:
completion_pr:
merge_sha:
---

# Chronicle PostgreSQL persistence

## Goal

Persist Chronicle's three accepted data layers in PostgreSQL without collapsing their authority boundaries:

1. source-owned staged Source / Entity / Event / Claim records;
2. cross-source Resolution Links;
3. C0-T8 canonical Entity/Event membership and canonical Event relations.

The persistence layer is Chronicle application infrastructure. It must not read, write, import, or redefine Loom Runtime/Storage tables or migrations.

## Persistence boundary

Chronicle uses its own PostgreSQL database/schema and its own migrations. It may reuse the repository-managed PostgreSQL 18 + pgvector service operationally, but pgvector is not required by this task.

Production/application connection authority is `CHRONICLE_DATABASE_URL`. PostgreSQL integration tests may reuse the repository's PG18 control service only to create isolated temporary Chronicle databases.

The stored rows preserve accepted staged/resolution/publication semantics. SQL constraints may reject contradictions or corruption, but persistence does not re-resolve entities/events, synthesize truth, rewrite Claims, or choose new canonical identity.

## Implemented data model

The first schema covers:

- Chronicle migration filename/checksum history;
- idempotent artifact/import metadata;
- source bundle identity and immutable source payload;
- staged Entity/Event/Claim rows with their exact JSON payloads;
- Resolution artifact payload, Entity links, Event links, and warnings;
- canonical catalog payload;
- CanonicalEntity / CanonicalEvent identities with PostgreSQL 18 UUIDv7 checks;
- canonical representation membership;
- canonical `related_occurrence` relations and provenance to concrete Resolution artifact SHA + candidate rows.

Stable natural references remain `(bundle_label, record_ref)`. Canonical IDs remain the UUIDv7 values produced by C0-T8.

## Idempotency / immutability rule

For a stable persisted key:

- identical content is a no-op/reuse;
- different content is an explicit persistence conflict;
- existing canonical membership is never silently reassigned;
- a transaction either imports all staged + resolution + canonical data or commits none of it.

Artifact SHA-256 values are computed over canonical JSON serialization for replay/audit identity; they are not historical semantic authority.

## Implementation artifacts

- `apps/chronicle/persistence/migrations/0001_chronicle_v0.sql`;
- `apps/chronicle/persistence/common.py`;
- `apps/chronicle/persistence/migrations.py`;
- `apps/chronicle/persistence/staged_store.py`;
- `apps/chronicle/persistence/resolution_store.py`;
- `apps/chronicle/persistence/canonical_store.py`;
- `apps/chronicle/persistence/postgres_v0.py`;
- `apps/chronicle/persistence/chronicle_persist.py`;
- `apps/chronicle/persistence/test_postgres_v0.py`;
- `apps/chronicle/persistence/test_real_dataset_postgres.py`;
- `apps/chronicle/docs/persistence.md`;
- `.github/workflows/chronicle.yml`.

The CLI validates staged, resolution, and canonical artifacts against the accepted JSON Schemas before opening the database write path. The adapter itself preserves those accepted semantics and uses PostgreSQL constraints/referential integrity only to reject corruption or contradictory persistence.

## PostgreSQL 18 verification

The persistence suite is now routed through the dedicated `Chronicle` GitHub Actions workflow. It runs only for Chronicle persistence, Chronicle schema, retained acceptance-artifact, or workflow changes and uses the exact repository database image `pgvector/pgvector:0.8.6-pg18`.

The first synthetic PG18 evidence run (`33511422006`, job `99867742169`) identified PostgreSQL `18.6` and passed all four synthetic persistence tests (`Ran 4 tests in 0.524s`, `OK`). After the real C0-T7 acceptance artifacts were retained in Git, permanent Chronicle workflow run `33512350772`, job `99870875184` passed the synthetic suite plus the real-data round trip:

```text
test_canonical_membership_reassignment_rolls_back ... ok
test_conflicting_bundle_rewrite_rolls_back ... ok
test_import_is_idempotent_and_restart_safe ... ok
test_migration_checksum_drift_fails ... ok
test_real_wudi_wuzhu_dataset_round_trip ... ok

Ran 5 tests in 1.058s
OK
```

This verifies transaction/idempotency behavior, explicit immutable-content conflicts, reconnect-safe canonical membership, exact Claim JSON/evidence retrieval, `related_occurrence` separation/provenance, migration checksum drift rejection, and the accepted real two-source catalog against PostgreSQL 18.

## First real validation

The accepted C0-T7/C0-T8 artifacts are retained in Git as a Chronicle golden integration dataset:

```text
apps/chronicle/.artifacts/c0-t7/wudi/final.json
apps/chronicle/.artifacts/c0-t7/wuzhu/final.json
apps/chronicle/.artifacts/c0-t7/resolution/links.json
apps/chronicle/.artifacts/c0-t7/publication/catalog.json
```

The real PG18 round-trip test verifies all of the following after a fresh import, identical second import, and database reconnect:

- `source_bundles = 2`;
- `canonical_entities = 66`;
- `canonical_events = 45`;
- `canonical_event_relations = 2`;
- Resolution rows remain `10 Entity links + 10 Event links`;
- the second identical import is a no-op (`import_created = false`) and only one import-set row exists;
- every persisted Entity/Event representation maps to exactly the UUID from the accepted canonical catalog;
- the two 曹操 representations share one CanonicalEntity;
- the two 赤壁之战 representations share one CanonicalEvent;
- each of 襄阳、夏口、江陵、赤壁、合肥 remains two distinct CanonicalEntities across the two source bundles;
- 曹操进军江陵 and 曹操北还并留军守江陵、襄阳 remain distinct CanonicalEvents connected by `related_occurrence`;
- all staged Claim JSON payloads round-trip exactly, preserving source evidence/provenance;
- both accepted `related_occurrence` relations retain Resolution Link provenance.

## Non-goals

- Chronicle read API;
- UI;
- embeddings / vector indexes;
- semantic search / Q&A;
- background ingestion scheduling;
- truth synthesis;
- Loom Core/Runtime/Storage migration changes.

## Acceptance

- [x] Chronicle-owned PostgreSQL migrations exist;
- [x] staged, Resolution, and canonical layers have separate persisted tables/artifact records;
- [x] import is transaction-safe and idempotent;
- [x] conflicting rewrites fail explicitly;
- [x] canonical UUID stability survives reconnect/reimport;
- [x] PostgreSQL 18 integration tests pass;
- [x] real 武帝纪 + 吴主传 dataset is durably imported and inspected;
- [x] documentation records backup/replay ownership and the application-vs-Loom boundary;
- [ ] delivery PR is merged and post-merge Task Ledger reconciliation is complete.

## Progress Log

- 2026-09-01 — C0-T8 dependency became canonical-complete after delivery PR #476 and post-merge reconciliation PR #477. C0-T9 started with a Chronicle-owned Python/PostgreSQL adapter design and isolated application database boundary.
- 2026-09-01 — Implemented Chronicle-owned migration/checksum tracking, staged/Resolution/canonical stores, single-transaction import orchestration, `CHRONICLE_DATABASE_URL` CLI, and PG18 integration tests. All new Python files pass local `py_compile`.
- 2026-09-01 — GitHub Actions run `33511422006` started `pgvector/pgvector:0.8.6-pg18` / PostgreSQL 18.6 and completed all four synthetic Chronicle persistence integration tests successfully (`Ran 4 tests in 0.524s`, `OK`).
- 2026-09-01 — Retained the real C0-T7/C0-T8 artifacts as a versioned Chronicle golden integration dataset and added a dedicated Chronicle CI workflow plus real-data PostgreSQL test.
- 2026-09-01 — Chronicle workflow run `33512350772`, job `99870875184` completed all five PG18 tests successfully (`Ran 5 tests in 1.058s`, `OK`), including full real 武帝纪 + 吴主传 persistence/reconnect/semantic inspection. Implementation acceptance is complete; only delivery merge and post-merge Task Ledger reconciliation remain.
