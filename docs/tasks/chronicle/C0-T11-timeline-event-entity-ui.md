---
task: C0-T11
issue: 473
status: completed
depends_on: [C0-T10]
created_at: 2026-09-01
started_at: 2026-09-01
completed_at: 2026-09-01
completion_pr: 483
merge_sha: 2e0d6df818d20151615da63c47b2a82ee2c41686
---

# Chronicle Timeline, Event Detail, and Entity Detail UI

## Goal

Deliver Chronicle's first genuinely usable historical exploration UI on top of the C0-T10 read API.

Primary path:

```text
Timeline
  -> Event Detail
      -> source representations / Claims / exact evidence
      -> participant/place Entity Detail
      -> related-but-distinct Events
```

## Dependency baseline

C0-T10 is canonically complete on `main` after delivery PR #480 (`5786681ae4053d7b169d112caee82c74f26a6894`) and reconciliation PR #482 (`de6887bba46dd9010a3bfb0a4aa799b9ec1eeaed`).

The UI consumes only C0-T10 HTTP contracts:

- `GET /v0/timeline`;
- `GET /v0/events/{canonical_event_id}`;
- `GET /v0/entities/{canonical_entity_id}`.

It does not read Chronicle PostgreSQL, staged JSON artifacts, canonical catalog files, or ingestion output directly.

## UI/runtime choice

The repository had no Chronicle JavaScript framework/package-manager baseline. C0-T11 therefore uses a zero-build browser layer:

- semantic HTML;
- responsive CSS;
- native ES modules;
- same-origin `fetch()` against the C0-T10 API;
- the existing Python read server as static-file host / SPA fallback;
- Node's built-in test runner for pure UI rendering/navigation contracts, with no npm dependencies.

This keeps product semantics in C0-T10 and leaves the browser layer replaceable.

## Timeline

Implemented behavior:

- canonical Event cards render once per API item;
- historical years are displayed without fabricated month/day precision;
- source count/source titles remain visible;
- event cards navigate by canonical Event UUID;
- loading, empty, API-error and pagination states are explicit.

## Event Detail

The UI keeps these layers visually separate:

1. canonical presentation identity;
2. source-by-source Event representations;
3. direct Claims with exact evidence/provenance when those Claims exist;
4. participant and place links to canonical Entity pages;
5. related-but-distinct canonical Events;
6. Resolution decisions including uncertainty/non-merge signals.

No generated synthesis is presented as source text. Source representations do not fabricate Claims merely to make both sources look symmetric.

## Entity Detail

Implemented behavior:

- canonical Entity presentation name/type;
- source representations and direct Claims/evidence;
- chronological canonical Event trajectory;
- source involvement labels distinguishing participant roles from `as_place`;
- visible unresolved/uncertain identity links;
- navigation back to Event Detail.

## HTTP/static boundary

The C0-T10 Python server serves API routes exactly as before. Non-API GET routes serve the Chronicle browser application from `apps/chronicle/web/`.

Static serving:

- never opens PostgreSQL for HTML/CSS/JS assets;
- rejects path traversal;
- serves the SPA shell for `/`, `/timeline`, `/events/{uuid}`, and `/entities/{uuid}`;
- keeps `/v0/*` and `/healthz` under existing API semantics;
- returns method-not-allowed for non-GET UI/static requests;
- rejects malformed percent-encoded browser routes without escaping the application;
- emits `nosniff` on static responses.

## Final validation evidence

Delivery PR #483 was squash-merged to `main` as `2e0d6df818d20151615da63c47b2a82ee2c41686` after exact-current-head Chronicle workflow run `33524009993` / job `99910092736` passed completely on head `f8a1ccdf9be810ecdefeec35896994149209fa78` and merge candidate `44a1f6f915070f062c287173f3ffa02a692ba447`.

The final gate proved:

- PostgreSQL persistence regressions: **5/5 passed**;
- C0-T10 real-data read model plus HTTP/static boundary regressions: **15/15 passed**;
- native Node UI navigation/rendering/security contracts: **7/7 passed**;
- real two-source persistence: **66 CanonicalEntities, 45 CanonicalEvents, 2 related-occurrence relations**;
- real headless browser vertical slice: **PASS** with `/usr/bin/google-chrome`;
- 赤壁之战 canonical Event: `01a05cd7-439d-7071-bf00-86c664886b06`;
- 曹操 canonical Entity navigation: `01a05cd7-439d-7172-b459-8d0c0747f5f2`;
- 赤壁 place canonical Entity navigation: `01a05cd7-439d-7606-b619-24ee5ceb009f`;
- the browser smoke verified the canonical 赤壁 Event appears once while retaining both 武帝纪 and 吴主传 source representations;
- every direct Claim evidence excerpt actually present in the API is required to appear verbatim in the rendered DOM; the retained 赤壁 Event has one such direct evidence excerpt, rather than inventing a Claim for a source representation that has none;
- 曹操 trajectory, `as_place` navigation, uncertain same-name 赤壁 identity, and related-but-distinct 江陵 Events were exercised through the real HTTP server and browser DOM.

A separate server-level regression intentionally uses an unusable PostgreSQL endpoint and proves `/timeline`, Event SPA routes, and JS modules still return successfully while `/v0/timeline` remains database-backed and returns `503 database_unavailable`. `/healthz` preserves its existing `{"status":"ok"}` contract.

## Acceptance

- [x] Timeline UI works against C0-T10 API contracts;
- [x] Event Detail renders canonical/source/Claim/evidence/related/uncertainty layers;
- [x] Entity Detail renders canonical/source/trajectory/involvement/uncertainty layers;
- [x] same-origin static server never requires DB access for UI assets;
- [x] no UI code reads local artifact JSON or PostgreSQL directly;
- [x] responsive browser layout works at basic desktop/mobile widths;
- [x] pure UI contract tests cover navigation and key data states;
- [x] dedicated Chronicle CI runs UI contracts and real browser smoke in addition to PG18 read contracts;
- [x] product/UI documentation records implemented behavior and local run path;
- [x] first two-source vertical slice is executable end to end through PostgreSQL -> API -> HTTP -> ES modules -> headless Chrome;
- [ ] delivery PR #483 is merged and post-merge Task Ledger reconciliation is merged to `main`.

## Progress Log

- 2026-09-01 — C0-T10 became canonically complete after delivery PR #480 and reconciliation PR #482. C0-T11 started as a zero-build same-origin browser layer over the existing Chronicle read server.
- 2026-09-01 — Implemented Timeline, Event Detail, Entity Detail, responsive styling, API wiring, provenance/evidence rendering, related-event navigation, uncertainty presentation, safe static routing, and browser route parsing.
- 2026-09-01 — Added Python HTTP/static boundary regressions and native Node UI contracts. The server boundary proves UI/static GETs do not require PostgreSQL while `/v0/*` remains database-backed.
- 2026-09-01 — Strengthened the final gate to persist the retained 武帝纪 + 吴主传 golden world, start the real Chronicle server, and inspect real rendered DOM through headless Chrome. Intermediate failures corrected test assumptions without weakening source semantics: `/healthz` retained its existing payload and source representations were not forced to fabricate missing Claims.
- 2026-09-01 — Exact-current-head Chronicle run `33524009993` / job `99910092736` passed 5 persistence tests, 15 read/static tests, 7 Node UI tests, and the real browser vertical slice. Delivery PR #483 squash-merged as `2e0d6df818d20151615da63c47b2a82ee2c41686`.
- 2026-09-01 — Post-merge Task Ledger reconciliation opened to make C0-T11 completion canonical on `main`.

## Non-goals

- world map;
- relationship graph;
- semantic search/Q&A;
- learning paths;
- counterfactual UI;
- ingestion/admin console;
- frontend framework/design-system adoption merely for C0-T11.
