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
- `apps/chronicle/docs/persistence.md`.

The CLI validates staged, resolution, and canonical artifacts against the accepted JSON Schemas before opening the database write path. The adapter itself preserves those accepted semantics and uses PostgreSQL constraints/referential integrity only to reject corruption or contradictory persistence.

## First real validation

Use the already accepted artifacts:

```text
apps/chronicle/.artifacts/c0-t7/wudi/final.json
apps/chronicle/.artifacts/c0-t7/wuzhu/final.json
apps/chronicle/.artifacts/c0-t7/resolution/links.json
apps/chronicle/.artifacts/c0-t7/publication/catalog.json
```

Verify:

- import succeeds against PostgreSQL 18;
- rerunning the same import is idempotent;
- reconnect/reopen returns the same canonical UUIDs;
- both source representations remain independently queryable;
- Claims retain exact source evidence/provenance in their stored payload;
- the two `related_occurrence` pairs remain distinct canonical Events with relations;
- the five uncertain same-name place pairs remain unresolved/unmerged in persisted data.

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
- [ ] import is transaction-safe and idempotent;
- [ ] conflicting rewrites fail explicitly;
- [ ] canonical UUID stability survives reconnect/reimport;
- [ ] PostgreSQL 18 integration tests pass;
- [ ] real 武帝纪 + 吴主传 dataset is durably imported and inspected;
- [x] documentation records backup/replay ownership and the application-vs-Loom boundary;
- [ ] delivery PR is merged and post-merge Task Ledger reconciliation is complete.

## Progress Log

- 2026-09-01 — C0-T8 dependency became canonical-complete after delivery PR #476 and post-merge reconciliation PR #477. C0-T9 started with a Chronicle-owned Python/PostgreSQL adapter design and isolated application database boundary.
- 2026-09-01 — Implemented Chronicle-owned migration/checksum tracking, staged/Resolution/canonical stores, single-transaction import orchestration, `CHRONICLE_DATABASE_URL` CLI, and PG18 integration tests. All new Python files pass local `py_compile`; PostgreSQL-dependent tests and the real two-source import remain intentionally unclaimed until executed against PG18.
