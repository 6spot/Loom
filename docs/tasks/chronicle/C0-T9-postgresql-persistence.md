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

## Planned data model

The first schema covers:

- applied Chronicle migrations;
- idempotent artifact/import metadata;
- source bundle identity and immutable source payload;
- staged Entity/Event/Claim rows with their exact JSON payloads;
- Resolution run payload, Entity links, Event links, and warnings;
- canonical catalog payload;
- CanonicalEntity / CanonicalEvent identities;
- canonical representation membership;
- canonical `related_occurrence` relations and resolution provenance.

Stable natural references remain `(bundle_label, record_ref)`. Canonical IDs remain the UUIDv7 values produced by C0-T8.

## Idempotency / immutability rule

For a stable persisted key:

- identical content is a no-op/reuse;
- different content is an explicit persistence conflict;
- existing canonical membership is never silently reassigned;
- a transaction either imports all staged + resolution + canonical data or commits none of it.

Artifact SHA-256 values are used for replay/audit identity; they are not historical semantic authority.

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

- [ ] Chronicle-owned PostgreSQL migrations exist;
- [ ] staged, Resolution, and canonical layers persist separately;
- [ ] import is transaction-safe and idempotent;
- [ ] conflicting rewrites fail explicitly;
- [ ] canonical UUID stability survives reconnect/reimport;
- [ ] PostgreSQL 18 integration tests pass;
- [ ] real 武帝纪 + 吴主传 dataset is durably imported and inspected;
- [ ] documentation records backup/replay ownership and the application-vs-Loom boundary;
- [ ] delivery PR is merged and post-merge Task Ledger reconciliation is complete.

## Progress Log

- 2026-09-01 — C0-T8 dependency became canonical-complete after delivery PR #476 and post-merge reconciliation PR #477. C0-T9 started with a Chronicle-owned Python/PostgreSQL adapter design and isolated application database boundary.
