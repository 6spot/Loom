# Chronicle Browser UI v0

C0-T11 adds Chronicle's first usable browser exploration surface over the C0-T10 read API.

## Implemented routes

```text
/timeline
/events/{canonical_event_id}
/entities/{canonical_entity_id}
```

`/` opens the Timeline. Direct navigation to Event and Entity URLs is supported by the same-origin SPA fallback.

The browser never reads Chronicle PostgreSQL, staged artifacts, canonical catalogs, or migrations. It uses only:

```text
GET /v0/timeline
GET /v0/events/{canonical_event_id}
GET /v0/entities/{canonical_entity_id}
```

## Runtime

Run the existing Chronicle server against an imported Chronicle database:

```bash
export CHRONICLE_DATABASE_URL='postgresql://.../chronicle'
python3 apps/chronicle/read_api/server.py --host 127.0.0.1 --port 8080
```

Then open:

```text
http://127.0.0.1:8080/timeline
```

The Python server keeps `/healthz` and `/v0/*` under C0-T10 JSON semantics. Other allowlisted GET routes serve `apps/chronicle/web/` without opening a PostgreSQL connection for the HTML/CSS/JavaScript request itself.

## Timeline

Timeline renders one card per canonical Event returned by C0-T10. Multiple source representations do not create duplicate cards.

A card shows:

- source-derived historical year or year range;
- presentation title and event type;
- representation count;
- source count and source titles;
- canonical Event navigation.

The year filter maps directly to C0-T10 `from_year` / `to_year`. Missing corpus data is shown as missing coverage, not as evidence that nothing happened.

## Event Detail

The Event page deliberately separates:

1. canonical Event presentation identity;
2. source representations;
3. direct Claims and exact evidence text;
4. participant Entity links;
5. place Entity links;
6. related-but-distinct Event links;
7. Resolution decisions and rationale/signals.

Source Event and Source metadata payloads remain reachable in collapsible raw-record views. Chronicle does not generate a synthetic narrative and label it as source truth.

## Entity Detail

The Entity page shows:

- canonical presentation name/type;
- chronological canonical Event trajectory;
- source-specific participant roles;
- `as_place` involvement when the Entity is used as a place reference;
- source Entity representations and direct Claims;
- uncertain / not-same identity Resolution decisions and links to the other canonical identity when available.

This keeps same-name uncertain places such as 赤壁 and 江陵 visibly separate while still making each place navigable to its Events.

## UI technology boundary

C0-T11 intentionally has no frontend package manager or build step:

- semantic HTML;
- responsive CSS;
- native browser ES modules;
- same-origin `fetch()`;
- Node built-in `--test` for pure rendering/navigation contracts.

This is a product-validation choice, not a permanent ban on a frontend framework. A later framework may replace the browser adapter without changing the C0-T10 API authority.

## Tests

The dedicated Chronicle workflow now runs three layers:

```text
C0-T9 PostgreSQL persistence contracts
C0-T10 read-model contracts against the retained real two-source world
C0-T11 UI rendering/navigation contracts
```

The UI tests cover:

- one Red Cliffs canonical Timeline card backed by two sources;
- source-separated Event evidence;
- canonical 曹操 Entity navigation;
- related Jiangling Event navigation;
- `as_place` trajectory semantics;
- uncertain same-name place identity;
- HTML escaping;
- static-route traversal rejection;
- prohibition on artifact/database escape hatches in production web code.

## Scope intentionally deferred

Not part of C0-T11:

- map;
- relationship graph;
- search/Q&A;
- learning paths;
- counterfactual simulation;
- ingestion/admin UI.
