---
task: C0-T12
issue: 485
status: in_progress
depends_on: [C0-T11]
created_at: 2026-09-01
started_at: 2026-09-01
completed_at:
completion_pr:
merge_sha:
---

# Chronicle Search and Historical Entry

## Goal

Make the completed Chronicle historical world directly discoverable by a user who knows a person, place, event, or historical term but does not know where it sits on the Timeline.

Primary flow:

```text
Search
  -> canonical Entity / Event result
      -> existing Entity Detail / Event Detail
      -> source representations / Claims / evidence / uncertainty
```

## Dependency baseline

C0-T11 is canonical on `main` after delivery PR #483 (`2e0d6df818d20151615da63c47b2a82ee2c41686`) and reconciliation PR #484 (`53e3b3b51e166d2bb20495e2292aaa1165740696`).

C0-T12 reuses the Chronicle-owned PostgreSQL read boundary and the C0-T11 zero-build browser surface. It does not create a new historical authority layer.

## Search v0 choice

Start with deterministic lexical search rather than embeddings/vector search.

Reasons:

- the retained corpus is still small;
- lexical matching is directly explainable to users;
- no new migration/index infrastructure is needed to prove product value;
- canonical grouping already provides the key cross-source de-duplication behavior;
- FTS, trigram/fuzzy matching, transliteration, and vector retrieval can be introduced later from measured search failures rather than assumption.

## Read contract

`GET /v0/search?q=...&kind=all|entity|event&limit=...`

The v0 read model searches source-owned representations but returns canonical objects once.

Entity search surfaces:

- deterministic canonical display name;
- source `canonical_name`;
- source aliases;
- source mentions;
- source description as secondary text.

Event search surfaces:

- deterministic canonical display title;
- source title;
- source summary;
- original source time text;
- normalized year as secondary text.

## Ranking

Ranking is deterministic and intentionally small:

1. rank 0 — exact canonical display surface;
2. rank 1 — exact source primary surface (`canonical_name`, alias, title);
3. rank 2 — primary-surface prefix match;
4. rank 3 — primary-surface substring match;
5. rank 4 — secondary mention/description/summary/time match.

Ties use stable kind, display label, and canonical UUID ordering.

Every returned item includes `matched_surfaces` containing the source bundle/ref, source title, field, value, and match type where applicable. Search relevance therefore remains auditable rather than a hidden score.

## Browser surface

The common Chronicle header owns a same-origin search form reachable from Timeline, Event Detail, and Entity Detail.

`/search?q=...` renders mixed canonical Entity/Event results. Result cards:

- distinguish Entity from Event;
- navigate only through existing canonical `/entities/{id}` and `/events/{id}` routes;
- expose representation/source counts;
- expose Event time metadata;
- retain an uncertainty badge for Entity results touched by accepted `uncertain` cross-source identity links;
- allow users to expand “为什么命中” to inspect exact source match surfaces.

## Authority boundary

C0-T12:

- reads only Chronicle-owned PostgreSQL;
- performs SELECT-only deterministic presentation/search work;
- does not read `.artifacts` from browser code;
- does not rerun ingestion, resolution, or publication;
- does not generate canonical IDs;
- does not synthesize historical truth;
- does not require pgvector;
- does not change Loom Core/Runtime/Storage authority.

## First real validation

Use the retained 武帝纪 + 吴主传 persisted world and prove:

- `曹操` returns one canonical Entity backed by both sources;
- `赤壁之战` returns one canonical Event backed by both sources;
- `赤壁` returns the Event plus two distinct uncertain place Entity identities rather than collapsing the places;
- `江陵` returns the two related-but-distinct Events separately;
- at least one real alias/mention surface resolves to its canonical Entity;
- `/search` remains a static browser route independent from database connectivity while `/v0/search` remains database-backed;
- clicking search results uses existing C0-T11 canonical routes.

## Acceptance

- [ ] deterministic lexical search read model exists;
- [ ] `/v0/search` validates query/kind/limit and returns canonical de-duplicated results;
- [ ] exact/prefix/substring/secondary ranking is deterministic and explainable;
- [ ] matched source surfaces remain visible in the response;
- [ ] uncertain same-name Entity identities remain distinct and visibly uncertain;
- [ ] browser search is reachable from all existing Chronicle pages;
- [ ] mixed search results navigate to existing Event/Entity Detail routes;
- [ ] empty/no-result/error states are explicit;
- [ ] PostgreSQL 18 real-data tests cover 曹操、赤壁之战、赤壁、江陵 and alias/mention lookup;
- [ ] Node/static/server tests cover the search browser boundary and escaping;
- [ ] Chronicle CI passes the full persistence/read/search/UI suite;
- [ ] search product/API documentation is updated;
- [ ] delivery PR is merged and post-merge Task Ledger reconciliation is complete.

## Non-goals

- semantic/vector search;
- open-ended Q&A;
- generated historical summaries;
- typo correction;
- fuzzy transliteration;
- map or graph search;
- new search-specific PostgreSQL migrations before product evidence requires them.
