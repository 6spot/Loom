# Chronicle Read Model / API v0

C0-T10 exposes the persisted Chronicle world as deterministic read-only application contracts for Timeline, Event Detail, and Entity Detail.

## Authority boundary

The read API reads only Chronicle-owned C0-T9 PostgreSQL tables. It does not run migrations, import artifacts, call a model, generate canonical UUIDs, or rewrite staged Source / Entity / Event / Claim data.

Canonical IDs are navigation identities. Display labels are deterministic presentation conveniences derived from source representations and are not identity or truth authority. Every detail response keeps source-owned payloads and evidence available separately.

Production connectivity uses `CHRONICLE_DATABASE_URL`.

## HTTP surface

```text
GET /healthz
GET /v0/timeline?from_year=208&to_year=208&limit=50&offset=0
GET /v0/events/{canonical_event_id}
GET /v0/entities/{canonical_entity_id}
```

The transport is intentionally thin and framework-free. `ChronicleReadRepository` is the application contract; the standard-library HTTP server is replaceable without changing read semantics.

Run locally against an already migrated/imported Chronicle database:

```bash
export CHRONICLE_DATABASE_URL='postgresql://.../chronicle'
python3 apps/chronicle/read_api/server.py --host 127.0.0.1 --port 8080
```

Requests execute in read-only PostgreSQL transactions.

## Timeline

Timeline emits each CanonicalEvent exactly once, even when multiple sources have representations of that occurrence. `from_year` / `to_year` use an inclusive presentation window. `limit` is `1..200`; `offset` is non-negative.

Canonical time is not synthesized. The card time window is derived from normalized years on all source Event representations:

- one observed normalized year -> `single_year`;
- differing observed source years -> `source_range` with min/max;
- no normalized year -> `unknown`.

Example for the accepted Red Cliffs event:

```json
{
  "schema": "chronicle.timeline",
  "version": "0.1",
  "query": {
    "from_year": 208,
    "to_year": 208,
    "limit": 50,
    "offset": 0
  },
  "items": [
    {
      "canonical_event_id": "01a05cd7-439d-7071-bf00-86c664886b06",
      "display": {
        "title": "赤壁之战",
        "type": "battle"
      },
      "time": {
        "start_year": 208,
        "end_year": 208,
        "status": "single_year"
      },
      "representation_count": 2,
      "source_count": 2,
      "source_titles": [
        "三国志·吴书·吴主传",
        "三国志·魏书·武帝纪"
      ]
    }
  ]
}
```

## Event Detail

Event Detail returns the CanonicalEvent summary plus all staged source representations. Each representation contains the source record, exact staged Event payload, and all direct staged Claims that reference that source Event. Claim payloads include their original evidence text and locator unchanged.

It also returns:

- canonicalized participants with source-specific roles;
- canonicalized places with source-specific references;
- Resolution Links involving any representation, including decision/rationale/signals;
- `related_occurrence` canonical Events with Resolution provenance.

Shape:

```json
{
  "schema": "chronicle.event-detail",
  "version": "0.1",
  "canonical_event_id": "01a05cd7-439d-7071-bf00-86c664886b06",
  "display": {"title": "赤壁之战", "type": "battle"},
  "representations": [
    {
      "bundle": "wudi",
      "ref": "evt_022",
      "source": {
        "bundle": "wudi",
        "ref": "src_001",
        "title": "三国志·魏书·武帝纪",
        "record": {}
      },
      "event": {},
      "claims": [
        {
          "bundle": "wudi",
          "ref": "clm_024",
          "claim": {
            "predicate": "outcome",
            "evidence": {
              "text": "...",
              "source_ref": "src_001",
              "locator": {}
            }
          }
        }
      ]
    },
    {
      "bundle": "wuzhu",
      "ref": "evt_016",
      "source": {},
      "event": {},
      "claims": []
    }
  ],
  "participants": [],
  "places": [],
  "related_events": [],
  "resolution_links": []
}
```

The abbreviated `{}` values above mean the API returns the full persisted source-owned payload; they are shortened only in this documentation example.

## Entity Detail

Entity Detail returns the canonical navigation identity plus all source-owned Entity representations, direct Claims, Resolution Links, and canonical Events involving the Entity.

An Event can involve an Entity in either of two source-specific ways:

```json
{
  "source_involvements": [
    {
      "bundle": "wudi",
      "entity_ref": "ent_001",
      "event_ref": "evt_022",
      "participant_roles": ["commander"],
      "as_place": false
    }
  ]
}
```

For place Entities, `as_place: true` makes events using that source place reference visible even when the place is not an Event participant. This is important for places such as 赤壁 and 江陵.

The accepted 曹操 representations (`wudi:ent_001`, `wuzhu:ent_017`) appear under one CanonicalEntity. Conversely, the same-name place pairs 襄阳、夏口、江陵、赤壁、合肥 remain separate CanonicalEntities and expose their `uncertain` Resolution Link rather than being silently collapsed.

## Errors

The router returns stable JSON errors:

```json
{
  "schema": "chronicle.error",
  "version": "0.1",
  "error": {
    "code": "bad_request",
    "message": "..."
  }
}
```

- `400 bad_request` — invalid UUID/query parameters or contract input;
- `404 not_found` — route or canonical object does not exist;
- `405 method_not_allowed` — non-GET request.

## Verification dataset

The dedicated `Chronicle` GitHub Actions workflow loads the retained C0-T7/C0-T8 golden artifacts into an isolated PostgreSQL 18 database before read-model tests. The contract verifies Red Cliffs de-duplication and source evidence, Jiangling related-but-distinct navigation, 曹操 aggregation, uncertain same-name place separation, place-to-Event navigation, and HTTP error behavior without Luna/model calls.
