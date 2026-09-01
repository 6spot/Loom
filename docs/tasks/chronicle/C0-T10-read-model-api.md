---
task: C0-T10
issue: 472
status: in_progress
depends_on: [C0-T9]
created_at: 2026-09-01
started_at: 2026-09-01
completed_at:
completion_pr:
merge_sha:
---

# Chronicle read model and API

## Goal

Expose the C0-T9 PostgreSQL world through stable, deterministic read contracts for the first product path:

1. Timeline;
2. Event Detail;
3. Entity Detail.

The read layer presents canonical identities for navigation while preserving source-owned representations, Claims, evidence, and Resolution decisions as separately visible data.

## Dependency baseline

C0-T9 is canonically complete on `main`: delivery PR #478 merged as `c408757f56f8c3e1da76eb575e973d296024b9b4` and reconciliation PR #479 merged as `2b08babe6778a7b3d5df8d3612e442a515772ce8`.

C0-T10 reads only Chronicle-owned persisted tables. It does not re-run ingestion, resolution, publication, migrations, or model calls.

## API/runtime choice

The repository has no existing Chronicle Python web framework and no FastAPI/Flask/aiohttp dependency. C0-T10 therefore uses:

- a PostgreSQL read repository as the primary contract;
- deterministic Python response builders;
- a thin standard-library HTTP JSON adapter for `/v0/...` routes.

The HTTP adapter is deliberately replaceable. Product semantics live in the read repository/contracts, not in a web framework.

## Read-model principles

- canonical UUIDs are navigation identity, never names/titles;
- display names/titles are deterministic presentation labels derived from source representations;
- all source representations remain available on detail reads;
- source Claims and verbatim evidence remain source-owned and are never collapsed into synthetic truth;
- `related_occurrence` remains a relation between distinct canonical Events;
- `uncertain` / `not_same` Resolution Links remain visible and never imply a merge;
- Event time used for Timeline ordering is a presentation window over source normalized times, not a new canonical historical assertion.

## Timeline v0

`GET /v0/timeline`

Query parameters:

- `from_year` optional integer;
- `to_year` optional integer;
- `limit` default 50, bounded;
- `offset` default 0.

Each canonical Event appears once. A card exposes canonical ID, deterministic display title/type, a source-derived time window, source/representation count, and enough lightweight metadata for navigation.

Known-time events sort before unknown-time events. A year filter includes an Event when its source-derived year window overlaps the requested range. Unknown-time Events are excluded when an explicit year range is supplied.

## Event Detail v0

`GET /v0/events/{canonical_event_id}`

Returns:

- canonical Event ID;
- deterministic display title/type and source-derived time window;
- every staged Event representation with Source metadata;
- Claims directly referencing each Event representation, including exact evidence/provenance;
- canonical participant mappings and source-specific roles;
- related canonical Events;
- all Event Resolution Links touching the canonical Event's representations, including uncertainty/non-merge decisions.

## Entity Detail v0

`GET /v0/entities/{canonical_entity_id}`

Returns:

- canonical Entity ID;
- deterministic presentation name/type;
- every staged Entity representation with Source metadata;
- canonical Events involving those representations, including source-specific roles;
- Claims directly referencing those Entity representations;
- all Entity Resolution Links touching those representations, including `uncertain`/`not_same` links and the other canonical identity when available.

This is how same-name uncertain places remain visibly distinct rather than silently collapsed.

## First real validation

Use the retained C0-T7/C0-T8 golden dataset persisted into PostgreSQL 18 and prove:

- Timeline contains the canonical 赤壁之战 exactly once;
- Red Cliffs Event Detail exposes both 武帝纪 and 吴主传 staged Event representations plus source Claims/evidence;
- 曹操进军江陵 and 曹操北还并留军守江陵、襄阳 remain distinct and navigably related;
- 曹操 Entity Detail contains both source representations under one canonical UUID;
- 襄阳、夏口、江陵、赤壁、合肥 uncertain same-name source records remain separate canonical Entity details with visible `uncertain` Resolution Links;
- every returned Claim preserves the exact persisted evidence payload.

## Non-goals

- browser UI;
- write/admin API;
- embeddings/vector search;
- semantic Q&A;
- generated authoritative narrative;
- Loom Core/Runtime/Storage changes.

## Acceptance

- [ ] stable JSON/read-model contracts exist for Timeline, Event Detail, and Entity Detail;
- [ ] repository/API reads only persisted Chronicle authority;
- [ ] canonical vs source-owned representations remain distinguishable;
- [ ] detail reads expose exact Claim evidence/provenance;
- [ ] related vs same occurrence and uncertain identity semantics are preserved;
- [ ] deterministic PostgreSQL 18 integration tests cover the retained two-source world;
- [ ] API documentation includes concrete real-data response examples;
- [ ] delivery PR is merged and post-merge Task Ledger reconciliation is complete.
