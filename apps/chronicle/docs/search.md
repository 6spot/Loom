# Chronicle Search v0

Chronicle Search v0 is the first historical entry surface after the Timeline/Event/Entity vertical slice.

## User path

The browser header exposes a search field on every Chronicle page. Submitting a term opens:

```text
/search?q=曹操
```

The browser then reads:

```text
GET /v0/search?q=曹操&kind=all&limit=20
```

Search results navigate only to existing canonical routes:

- `/events/{canonical_event_id}`;
- `/entities/{canonical_entity_id}`.

Search does not create a separate detail model.

## API

`GET /v0/search`

Parameters:

- `q` — required non-empty search text, maximum 100 characters;
- `kind` — `all` (default), `entity`, or `event`;
- `limit` — default 20, range 1..50.

Example response shape:

```json
{
  "schema": "chronicle.search",
  "version": "0.1",
  "query": {"q": "曹操", "kind": "all", "limit": 20},
  "page": {"total": 1, "returned": 1, "has_more": false},
  "items": [
    {
      "kind": "entity",
      "canonical_id": "...",
      "display": {"name": "曹操", "type": "person"},
      "representation_count": 2,
      "source_count": 2,
      "source_titles": ["三国志·吴书·吴主传", "三国志·魏书·武帝纪"],
      "identity_uncertain": false,
      "navigation_path": "/entities/...",
      "match": {
        "rank": 0,
        "matched_surfaces": [
          {
            "rank": 1,
            "match": "exact",
            "field": "entity.canonical_name",
            "value": "曹操",
            "bundle": "wudi",
            "ref": "ent_...",
            "source_title": "三国志·魏书·武帝纪"
          }
        ]
      }
    }
  ]
}
```

## Ranking

Lower rank wins:

| Rank | Meaning |
| ---: | --- |
| 0 | exact canonical display name/title |
| 1 | exact source primary surface: Entity canonical name/alias or Event title |
| 2 | prefix match on a primary surface |
| 3 | substring match on a primary surface |
| 4 | secondary source surface: mention, description, Event summary, source time text, normalized year |

Ties are deterministic by result kind, display label, and canonical UUID.

This ranking is intentionally explainable. It is not an ML relevance score.

## Canonical de-duplication

Search scans source-owned representations but groups matches by canonical UUID before returning results.

Therefore:

- two source representations of 曹操 return one Entity result;
- two source representations of 赤壁之战 return one Event result;
- two uncertain same-name 赤壁 place representations remain two different Entity results because publication did not merge them;
- related-but-distinct 江陵 Events remain separate results.

## Match provenance

`matched_surfaces` records the exact surfaces that caused a result to appear:

- bundle label;
- staged record ref;
- Source title;
- matched field;
- original matched value;
- match class (`exact`, `prefix`, or `substring`).

The browser exposes these under “为什么命中”. This keeps discovery behavior auditable and makes future ranking changes reviewable.

## Uncertainty

Entity results include `identity_uncertain=true` when a canonical representation participates in an accepted cross-source Resolution Link whose decision is `uncertain`.

Search never converts an uncertain identity into a merged identity merely because the names match.

## Data boundary

Search v0:

- reads Chronicle-owned PostgreSQL using the same connection as the C0-T10 repository;
- performs no writes;
- does not read local artifact JSON from browser code;
- does not run ingestion, resolution, or canonical publication;
- does not use pgvector, embeddings, LLM ranking, or generated answers.

No migration is added for v0. The retained corpus is intentionally small enough to validate the product path before introducing search infrastructure.

## Validation

Chronicle CI discovers:

```bash
python -m unittest discover -s apps/chronicle/read_api -p 'test_*.py' -v
node --test apps/chronicle/web/test_*.mjs
```

The real PostgreSQL search tests persist the retained 武帝纪 + 吴主传 world and verify canonical de-duplication, uncertain-place separation, related Event separation, alias/mention discovery, router validation, and match provenance.
