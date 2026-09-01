---
task: C0-T11
issue: 473
status: in_progress
depends_on: [C0-T10]
created_at: 2026-09-01
started_at: 2026-09-01
completed_at:
completion_pr:
merge_sha:
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

It must not read Chronicle PostgreSQL, staged JSON artifacts, canonical catalog files, or ingestion output directly.

## UI/runtime choice

The repository has no Chronicle JavaScript framework/package-manager baseline. C0-T11 therefore uses a zero-build browser layer:

- semantic HTML;
- responsive CSS;
- native ES modules;
- same-origin `fetch()` against the C0-T10 API;
- the existing Python read server as static-file host / SPA fallback;
- Node's built-in test runner for pure UI rendering/navigation contracts, with no npm dependencies.

This keeps product semantics in C0-T10 and leaves the browser layer replaceable.

## Timeline

Required:

- canonical Event cards rendered once per API item;
- historical year display without fabricated month/day precision;
- source count/source titles visible without overwhelming the card;
- compact event type and provenance cues;
- event cards navigate by canonical Event UUID;
- loading, empty, API-error and pagination states are explicit.

## Event Detail

Required layers remain visually separated:

1. canonical presentation identity;
2. source-by-source Event representations;
3. direct Claims with exact evidence/provenance;
4. participant and place links to canonical Entity pages;
5. related-but-distinct canonical Events;
6. Resolution decisions including uncertainty/non-merge signals.

No generated synthesis may masquerade as source text.

## Entity Detail

Required:

- canonical Entity presentation name/type;
- source representations and direct Claims/evidence;
- chronological canonical Event trajectory;
- source involvement labels distinguishing participant roles from `as_place`;
- visible unresolved/uncertain identity links;
- navigation back to Event Detail.

## HTTP/static boundary

The C0-T10 Python server serves API routes exactly as before. Non-API GET routes serve the Chronicle browser application from `apps/chronicle/web/`.

Static serving must:

- never open PostgreSQL for HTML/CSS/JS assets;
- reject path traversal;
- serve the SPA shell for `/`, `/timeline`, `/events/{uuid}`, and `/entities/{uuid}`;
- keep `/v0/*` and `/healthz` under existing API semantics;
- return method-not-allowed for non-GET UI/static requests.

## Validation

Use the retained 武帝纪 + 吴主传 persisted world and prove:

- Timeline renders one canonical 赤壁之战 card backed by two sources;
- the 赤壁 Event page exposes both source representations and exact evidence;
- participant 曹操 links to one canonical Entity page with cross-source trajectory;
- related Jiangling Events remain separate links;
- uncertain same-name places show uncertainty rather than merged certainty;
- place Entity navigation reaches Events through `as_place`;
- UI modules do not reference `.artifacts`, migration SQL, or database connection variables.

### Delivery evidence in progress

PR #483 has already passed the PostgreSQL 18 persistence suite, the C0-T10 read/static suite, and native Node UI rendering/navigation contracts on its merge ref. The final delivery gate is now stronger than those unit/contract checks: Chronicle CI persists the retained two-source golden world, starts the real Chronicle HTTP server, and runs `apps/chronicle/web/browser_smoke.py` through the runner's headless Chrome. The acceptance checkboxes remain open until that browser gate is green on the current delivery head and the post-merge ledger reconciliation is complete.

## Acceptance

- [ ] Timeline UI works against C0-T10 API contracts;
- [ ] Event Detail renders canonical/source/Claim/evidence/related/uncertainty layers;
- [ ] Entity Detail renders canonical/source/trajectory/involvement/uncertainty layers;
- [ ] same-origin static server never requires DB access for UI assets;
- [ ] no UI code reads local artifact JSON or PostgreSQL directly;
- [ ] responsive browser layout works at basic desktop/mobile widths;
- [ ] pure UI contract tests cover navigation and key data states;
- [ ] dedicated Chronicle CI runs UI contracts in addition to PG18 read contracts;
- [ ] product/UI documentation records implemented behavior and local run path;
- [ ] first two-source vertical slice is manually usable end to end;
- [ ] delivery PR is merged and post-merge Task Ledger reconciliation is complete.

## Non-goals

- world map;
- relationship graph;
- semantic search/Q&A;
- learning paths;
- counterfactual UI;
- ingestion/admin console;
- frontend framework/design-system adoption merely for C0-T11.
