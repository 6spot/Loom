"""Grounded, bounded Historical Moment projection over published Chronicle data.

A Historical Moment is a read-only view of what the current Chronicle corpus
represents for one selected year or bounded period. It is deliberately not a
complete Historical World State: absent data remains absent and no territorial,
location, office, troop, or political state is inferred to fill gaps.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from coverage import _entity_rows, _event_rows, _group_rows, _latest_catalog_sha, build_coverage
from read_common import ReadModelError, entity_display, event_display, normalized_year
from reader_presentation import latest_reader_presentation


HISTORICAL_MOMENT_SCHEMA = "chronicle.historical-moment"
HISTORICAL_MOMENT_VERSION = "0.1"
MAX_PERIOD_YEARS = 100
MAX_EVENT_LIMIT = 100

WORLD_STATE_LIMITATION = (
    "This response is a Historical Moment Projection over the published Chronicle corpus, "
    "not a complete Historical World State. Unsupported territorial control, precise person "
    "locations, office state, troop counts, political ownership, and other missing state are "
    "not inferred."
)


def _validate_year(value: int, name: str) -> None:
    if not isinstance(value, int):
        raise ReadModelError(f"{name} must be an integer")
    if value < -10000 or value > 10000:
        raise ReadModelError(f"{name} is outside the supported reporting range")


def _period(
    *, year: int | None, from_year: int | None, to_year: int | None
) -> tuple[int, int, str]:
    if year is not None:
        if from_year is not None or to_year is not None:
            raise ReadModelError("year cannot be combined with from_year or to_year")
        _validate_year(year, "year")
        return year, year, "year"
    if from_year is None or to_year is None:
        raise ReadModelError("provide year or both from_year and to_year")
    _validate_year(from_year, "from_year")
    _validate_year(to_year, "to_year")
    if from_year > to_year:
        raise ReadModelError("from_year must be <= to_year")
    if to_year - from_year + 1 > MAX_PERIOD_YEARS:
        raise ReadModelError(f"period must span at most {MAX_PERIOD_YEARS} years")
    return from_year, to_year, "period"


def _pagination(limit: int, offset: int) -> None:
    if not isinstance(limit, int) or limit < 1 or limit > MAX_EVENT_LIMIT:
        raise ReadModelError(f"limit must be between 1 and {MAX_EVENT_LIMIT}")
    if not isinstance(offset, int) or offset < 0:
        raise ReadModelError("offset must be >= 0")


def _source_metadata(conn) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT bundle_label, source_ref, source_title
        FROM chronicle.source_bundles
        ORDER BY bundle_label
        """
    ).fetchall()
    return {
        str(row[0]): {"ref": row[1], "title": row[2]}
        for row in rows
    }


def _claim_index(conn) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Index persisted Claims by every directly referenced source record."""
    result: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    rows = conn.execute(
        """
        SELECT bundle_label, record_ref, payload
        FROM chronicle.staged_claims
        ORDER BY bundle_label, record_ref
        """
    ).fetchall()
    for bundle, claim_ref, payload in rows:
        if not isinstance(payload, dict):
            continue
        item = {"bundle": str(bundle), "ref": str(claim_ref), "claim": payload}
        for endpoint in (payload.get("subject"), payload.get("object")):
            if not isinstance(endpoint, dict):
                continue
            kind = endpoint.get("kind")
            ref = endpoint.get("ref")
            if kind in {"event_ref", "entity_ref"} and isinstance(ref, str) and ref:
                result[(str(bundle), ref)].append(item)
    return dict(result)


def _time_contract(rows: list[dict[str, Any]]) -> dict[str, Any]:
    observations = []
    observed_years: set[int] = set()
    for row in rows:
        payload = row["payload"]
        year = normalized_year(payload)
        if year is not None:
            observed_years.add(year)
        raw_time = payload.get("time")
        observations.append(
            {
                "bundle": row["bundle"],
                "ref": row["ref"],
                "normalized_year": year,
                "source_time": raw_time if isinstance(raw_time, dict) else None,
            }
        )
    years = sorted(observed_years)
    if not years:
        status = "unknown"
    elif len(years) == 1:
        status = "single_observed_year"
    else:
        status = "source_disagreement"
    return {
        "status": status,
        "observed_years": years,
        "start_year": years[0] if years else None,
        "end_year": years[-1] if years else None,
        "observations": observations,
    }


def _in_period(rows: list[dict[str, Any]], start_year: int, end_year: int) -> bool:
    return any(
        start_year <= year <= end_year
        for row in rows
        if (year := normalized_year(row["payload"])) is not None
    )


def _direct_event_claims(
    rows: list[dict[str, Any]],
    claim_index: dict[tuple[str, str], list[dict[str, Any]]],
    source_meta: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        for item in claim_index.get((row["bundle"], row["ref"]), []):
            key = (item["bundle"], item["ref"])
            enriched = dict(item)
            enriched["source"] = source_meta.get(item["bundle"], {"ref": None, "title": None})
            found[key] = enriched
    return [found[key] for key in sorted(found)]


def _event_card(
    conn,
    canonical_id: str,
    rows: list[dict[str, Any]],
    claim_index: dict[tuple[str, str], list[dict[str, Any]]],
    source_meta: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    claims = _direct_event_claims(rows, claim_index, source_meta)
    return {
        "canonical_event_id": canonical_id,
        "display": event_display(row["payload"] for row in rows),
        "time": _time_contract(rows),
        "representation_count": len(rows),
        "source_count": len({row["bundle"] for row in rows}),
        "sources": [
            {"bundle": label, **source_meta.get(label, {"ref": None, "title": None})}
            for label in sorted({row["bundle"] for row in rows})
        ],
        "representations": [
            {
                "bundle": row["bundle"],
                "ref": row["ref"],
                "event": row["payload"],
            }
            for row in rows
        ],
        "claims": claims,
        "reader_presentation": latest_reader_presentation(
            conn, target_kind="event", canonical_id=canonical_id
        ),
    }


def _endpoint_entity_ref(endpoint: Any) -> str | None:
    if not isinstance(endpoint, dict) or endpoint.get("kind") != "entity_ref":
        return None
    ref = endpoint.get("ref")
    return ref if isinstance(ref, str) and ref else None


def _related_entities(
    conn,
    event_cards: list[dict[str, Any]],
    event_grouped: dict[str, list[dict[str, Any]]],
    entity_grouped: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rep_to_entity: dict[tuple[str, str], str] = {}
    for canonical_id, rows in entity_grouped.items():
        for row in rows:
            rep_to_entity[(row["bundle"], row["ref"])] = canonical_id

    links: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    unresolved: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    def remember(
        event_id: str,
        bundle: str,
        entity_ref: str,
        *,
        participant_role: Any = None,
        as_place: bool = False,
        claim_ref: str | None = None,
    ) -> None:
        canonical_id = rep_to_entity.get((bundle, entity_ref))
        if canonical_id is None:
            key = (event_id, bundle, entity_ref, claim_ref or "")
            unresolved[key] = {
                "canonical_event_id": event_id,
                "bundle": bundle,
                "entity_ref": entity_ref,
                "participant_role": participant_role,
                "as_place": as_place,
                "claim_ref": claim_ref,
            }
            return
        entry = links[canonical_id].setdefault(
            event_id,
            {
                "canonical_event_id": event_id,
                "participant_roles": set(),
                "as_place": False,
                "claim_refs": set(),
            },
        )
        if isinstance(participant_role, str) and participant_role:
            entry["participant_roles"].add(participant_role)
        entry["as_place"] = entry["as_place"] or as_place
        if claim_ref:
            entry["claim_refs"].add((bundle, claim_ref))

    cards_by_id = {item["canonical_event_id"]: item for item in event_cards}
    for event_id in sorted(cards_by_id):
        for row in event_grouped[event_id]:
            bundle = row["bundle"]
            payload = row["payload"]
            for participant in payload.get("participants") or []:
                if not isinstance(participant, dict):
                    continue
                ref = participant.get("entity_ref")
                if isinstance(ref, str) and ref:
                    remember(
                        event_id,
                        bundle,
                        ref,
                        participant_role=participant.get("role"),
                    )
            for ref in payload.get("places") or []:
                if isinstance(ref, str) and ref:
                    remember(event_id, bundle, ref, as_place=True)
        for claim in cards_by_id[event_id]["claims"]:
            payload = claim["claim"]
            for endpoint in (payload.get("subject"), payload.get("object")):
                ref = _endpoint_entity_ref(endpoint)
                if ref:
                    remember(event_id, claim["bundle"], ref, claim_ref=claim["ref"])

    entities = []
    for canonical_id in sorted(links):
        rows = entity_grouped.get(canonical_id, [])
        if not rows:
            continue
        relations = []
        for event_id in sorted(links[canonical_id]):
            relation = links[canonical_id][event_id]
            relations.append(
                {
                    "canonical_event_id": event_id,
                    "participant_roles": sorted(relation["participant_roles"]),
                    "as_place": bool(relation["as_place"]),
                    "claim_refs": [
                        {"bundle": bundle, "ref": claim_ref}
                        for bundle, claim_ref in sorted(relation["claim_refs"])
                    ],
                }
            )
        display = entity_display(row["payload"] for row in rows)
        entities.append(
            {
                "canonical_entity_id": canonical_id,
                "display": display,
                "representation_count": len(rows),
                "source_count": len({row["bundle"] for row in rows}),
                "relations": relations,
                "reader_presentation": latest_reader_presentation(
                    conn, target_kind="entity", canonical_id=canonical_id
                ),
            }
        )

    unresolved_items = [unresolved[key] for key in sorted(unresolved)]
    return entities, unresolved_items


def build_historical_moment(
    conn,
    *,
    year: int | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Build a deterministic Historical Moment from SELECT-only published data."""
    start_year, end_year, query_kind = _period(
        year=year, from_year=from_year, to_year=to_year
    )
    _pagination(limit, offset)

    catalog_sha = _latest_catalog_sha(conn)
    event_grouped = _group_rows(_event_rows(conn, catalog_sha))
    entity_grouped = _group_rows(_entity_rows(conn, catalog_sha))
    source_meta = _source_metadata(conn)
    claim_index = _claim_index(conn)

    matching_ids = [
        canonical_id
        for canonical_id in sorted(event_grouped)
        if _in_period(event_grouped[canonical_id], start_year, end_year)
    ]

    def event_sort_key(canonical_id: str) -> tuple[Any, ...]:
        rows = event_grouped[canonical_id]
        years = sorted(
            {
                year
                for row in rows
                if (year := normalized_year(row["payload"])) is not None
            }
        )
        display = event_display(row["payload"] for row in rows)
        return (
            years[0] if years else 10001,
            years[-1] if years else 10001,
            display.get("title") or "",
            canonical_id,
        )

    matching_ids.sort(key=event_sort_key)
    total = len(matching_ids)
    page_ids = matching_ids[offset : offset + limit]
    event_cards = [
        _event_card(
            conn,
            canonical_id,
            event_grouped[canonical_id],
            claim_index,
            source_meta,
        )
        for canonical_id in page_ids
    ]
    entities, unresolved_refs = _related_entities(
        conn, event_cards, event_grouped, entity_grouped
    )
    places = [item for item in entities if item["display"].get("type") == "place"]
    polities = [item for item in entities if item["display"].get("type") == "polity"]
    other_entities = [
        item
        for item in entities
        if item["display"].get("type") not in {"place", "polity"}
    ]

    coverage = build_coverage(conn, from_year=start_year, to_year=end_year)
    temporal_disagreements = sum(
        1 for item in event_cards if item["time"]["status"] == "source_disagreement"
    )
    represented_sources = sorted(
        {
            source["bundle"]
            for event in event_cards
            for source in event["sources"]
        }
    )

    return {
        "schema": HISTORICAL_MOMENT_SCHEMA,
        "version": HISTORICAL_MOMENT_VERSION,
        "authority": {
            "kind": "derived_projection",
            "historical_world_state": False,
            "historical_truth": False,
            "mutates_history": False,
            "publication_boundary": "latest_canonical_catalog",
            "limitation": WORLD_STATE_LIMITATION,
        },
        "query": {
            "kind": query_kind,
            "year": year,
            "from_year": start_year,
            "to_year": end_year,
            "limit": limit,
            "offset": offset,
        },
        "catalog": {
            "status": "published" if catalog_sha is not None else "unknown",
            "latest_catalog_sha256": catalog_sha,
        },
        "page": {
            "total_events": total,
            "returned_events": len(event_cards),
            "has_more": offset + len(event_cards) < total,
        },
        "events": event_cards,
        "entities": other_entities,
        "places": places,
        "polities": polities,
        "sources": [
            {"bundle": label, **source_meta.get(label, {"ref": None, "title": None})}
            for label in represented_sources
        ],
        "uncertainty": {
            "temporal_disagreement_event_count": temporal_disagreements,
            "unresolved_entity_reference_count": len(unresolved_refs),
            "unresolved_entity_references": unresolved_refs,
            "absence_is_not_historical_absence": True,
        },
        "coverage": coverage,
    }
