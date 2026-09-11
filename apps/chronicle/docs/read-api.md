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
GET /v0/chapters?limit=50&cursor=…
GET /v0/chapters/{publication_id}
GET /v0/chapters/{publication_id}/sources/{anchor_id}?view=window|chapter&cursor=…&limit=…
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

## Public chapters (C2-R1-T14)

Read-only public surface over already-published chapters
(`chapter-production.md` §7). Python-internal paths are the fixed
`/v0/chapters*` above on the shared public router; `server.py` injects
the configured `storage_dir` into the source reader, and the Rust
`/api/v1/public/chapters*` frontend mapping belongs to T17. All GETs
run in read-only transactions, never call a model, allocate canonical
IDs, or repair data.

- `GET /v0/chapters?limit=50&cursor=…` — published-only directory with
  document/chapter titles, `revision_no`, `publication_id` and stable
  keyset order `(document_id, revision_no, chapter_index,
  publication_id)`; `limit` is `1..100`, cursor is versioned and
  scope-bound, `next_cursor` is null at the tail. Accepted-but-
  unpublished artifacts never appear here.
- `GET /v0/chapters/{publication_id}` — the complete ordered
  translation blocks plus `source_overview` and the precomputed
  (assembled-remapped, catalog-canonicalized) entity/event references.
  The response must validate against the T01
  `validate_public_chapter_response` shape; it returns the full text
  or fails explicitly and never serves a summary, first paragraph, or
  blurb as the full text.
- `GET /v0/chapters/{publication_id}/sources/{anchor_id}?view=window|chapter`
  — the exact source text visible to that publication, served through
  the unique T10 `source_context` reader after verifying the anchor
  belongs to the addressed publication/artifact/revision. Window is
  ±400 code points clamped to the chapter; chapter pages hold at most
  16,000 code points with `has_more`/`next_cursor`. Old pages stay
  pinned to the old revision/hash; identical text under another
  publication never authorizes a read.

Error codes beyond the shared ones above:

- `404 not_found` — unknown publication, cross-publication anchor, or
  unknown version;
- `409 source_unavailable` — revision bytes missing or anchor without a
  chapter binding (never falls back to a newer revision);
- `409 source_mismatch` — source hash/range drift (never reads the new
  bytes as the old version);
- `409 reference_unmapped` / `reference_unavailable` /
  `catalog_unavailable` — a translation reference without its exact
  assembled/catalog mapping (never guessed or regenerated at read);
- `409 response_too_large` — the complete response exceeds the 8 MiB
  forwarding cap (explicit failure, never truncated).

Tests: `test_reader_chapters_postgres.py` (14 PG18 integration tests:
two revisions pinning old links, claim-less blocks, many-to-many ref
positions, drift/unavailable 409s, exact chapter paging, read-only +
no-model-call proof, same-job second assembled output isolation,
tampered-bundle explicit failure) and `test_reader_chapters_unit.py`
(cursor scope binding, size cap, method/route codes).

## Continuous reading (C2-R2-T09)

`continuous-reading.md` §6 fixes one public HTTP boundary: browsers call
the Rust `/api/v1/public/reading-*` surface; the Python sidecar serves
the matching `/v0/reading-*` contracts. Every read is snapshot-scoped:
the first stream-directory call resolves the newest catalog and returns
`snapshot.catalog_sha`, and later pages/previews/locators must send it
back explicitly.

```text
GET /v0/reading-streams?catalog=&limit=20&cursor=
GET /v0/reading-streams/{stream_id}?catalog=
GET /v0/reading-streams/{stream_id}/units?catalog=&limit=20&cursor=&direction=
GET /v0/reading-streams/{stream_id}/groups?catalog=&limit=50&cursor=&direction=
GET /v0/reading-streams/{stream_id}/locate?catalog=&unit_id=&limit=
GET /v0/reading-events/{event_id}/preview?catalog=
GET /v0/reading-events/{event_id}/targets?catalog=&limit=20&cursor=
```

- `limit` is `1..50` for body pages and locate, `1..100` for groups;
  cursors bind catalog, stream, direction and the last stable ordering
  key (`continuous-reading.md` §5-6).
- `catalog` is optional on the stream directory (first call resolves the
  newest snapshot) and required on `/reading-events/.../preview` and
  `/targets`; an unknown catalog is a `404`.
- Unknown or repeated query parameters, an invalid UUID/catalog, a
  missing required `catalog`, an out-of-range `limit` and a cursor from
  another scope are `400 bad_request`.
- Unknown or unpublished streams/units/events, an out-of-publication
  source anchor, and unknown subroutes are `404 not_found`.
- Non-GET methods are `405 method_not_allowed`.
- An internally inconsistent reading index is `500 internal_error`
  (explicit failure, never silently repaired).

The existing `GET /v0/events/{id}` and `GET /v0/entities/{id}` accept an
optional `catalog`. Without it the response is unchanged, including the
latest `reader_presentation` overlay. With it, source representations,
related objects and Resolution provenance are restricted to that
snapshot's members and `reader_presentation` is `null`: a Reader
Presentation has no snapshot binding, so the unbounded "latest"
projection is never mixed into a fixed snapshot view.

Tests: `test_reading_router_postgres.py` (route coverage, parameter/
method/error mapping, snapshot overlay suppression) and
`test_reading_source_context_postgres.py` (an accepted 0.2 artifact is
served through the same `source_context` reader and public source
route).

## Verification dataset

The dedicated `Chronicle` GitHub Actions workflow loads the retained C0-T7/C0-T8 golden artifacts into an isolated PostgreSQL 18 database before read-model tests. The contract verifies Red Cliffs de-duplication and source evidence, Jiangling related-but-distinct navigation, 曹操 aggregation, uncertain same-name place separation, place-to-Event navigation, and HTTP error behavior without Luna/model calls.
