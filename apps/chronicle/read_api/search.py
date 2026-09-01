"""Deterministic lexical search over Chronicle's persisted canonical world."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from read_common import READ_SCHEMA_VERSION, ReadModelError, entity_display, event_display, time_window


MAX_SEARCH_LIMIT = 50
MAX_QUERY_LENGTH = 100
VALID_KINDS = {"all", "entity", "event"}


def _query_text(value: str) -> str:
    if not isinstance(value, str):
        raise ReadModelError("q must be a string")
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        raise ReadModelError("q must not be empty")
    if len(cleaned) > MAX_QUERY_LENGTH:
        raise ReadModelError(f"q must be at most {MAX_QUERY_LENGTH} characters")
    return cleaned


def _match(value: Any, query: str, *, exact_rank: int, secondary: bool = False) -> tuple[int, str] | None:
    if not isinstance(value, str) or not value:
        return None
    haystack = value.casefold()
    needle = query.casefold()
    if secondary:
        return (4, "substring") if needle in haystack else None
    if haystack == needle:
        return exact_rank, "exact"
    if haystack.startswith(needle):
        return 2, "prefix"
    if needle in haystack:
        return 3, "substring"
    return None


def _surface(
    *,
    rank: int,
    match: str,
    field: str,
    value: str,
    bundle: str | None = None,
    ref: str | None = None,
    source_title: str | None = None,
) -> dict[str, Any]:
    return {
        "rank": rank,
        "match": match,
        "field": field,
        "value": value,
        "bundle": bundle,
        "ref": ref,
        "source_title": source_title,
    }


def _append_surface(
    surfaces: list[dict[str, Any]],
    value: Any,
    query: str,
    *,
    field: str,
    exact_rank: int,
    secondary: bool = False,
    bundle: str | None = None,
    ref: str | None = None,
    source_title: str | None = None,
) -> None:
    matched = _match(value, query, exact_rank=exact_rank, secondary=secondary)
    if matched is None:
        return
    rank, match = matched
    surfaces.append(
        _surface(
            rank=rank,
            match=match,
            field=field,
            value=value,
            bundle=bundle,
            ref=ref,
            source_title=source_title,
        )
    )


def _dedupe_surfaces(surfaces: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    found: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in surfaces:
        key = (
            item["rank"],
            item["match"],
            item["field"],
            item["value"],
            item.get("bundle"),
            item.get("ref"),
            item.get("source_title"),
        )
        found[key] = item
    return [
        found[key]
        for key in sorted(
            found,
            key=lambda value: (
                value[0],
                value[4] or "",
                value[5] or "",
                value[2],
                value[3],
            ),
        )
    ]


def _rows(conn, kind: str) -> list[dict[str, Any]]:
    if kind == "entity":
        table = "canonical_entity_representations"
        staged = "staged_entities"
    elif kind == "event":
        table = "canonical_event_representations"
        staged = "staged_events"
    else:
        raise ReadModelError(f"unsupported search kind {kind!r}")

    rows = conn.execute(
        f"""
        SELECT
            r.canonical_id::text,
            r.bundle_label,
            r.record_ref,
            s.payload,
            b.source_title
        FROM chronicle.{table} r
        JOIN chronicle.{staged} s
          ON s.bundle_label = r.bundle_label AND s.record_ref = r.record_ref
        JOIN chronicle.source_bundles b
          ON b.bundle_label = r.bundle_label
        ORDER BY r.canonical_id, r.bundle_label, r.record_ref
        """
    ).fetchall()
    return [
        {
            "canonical_id": row[0],
            "bundle": row[1],
            "ref": row[2],
            "payload": row[3],
            "source_title": row[4],
        }
        for row in rows
    ]


def _uncertain_entity_ids(conn) -> set[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT r.canonical_id::text
        FROM chronicle.canonical_entity_representations r
        JOIN chronicle.resolution_entity_links l
          ON (r.bundle_label = l.left_bundle_label AND r.record_ref = l.left_record_ref)
          OR (r.bundle_label = l.right_bundle_label AND r.record_ref = l.right_record_ref)
        WHERE l.decision = 'uncertain'
        ORDER BY r.canonical_id::text
        """
    ).fetchall()
    return {row[0] for row in rows}


def _entity_result(
    canonical_id: str,
    rows: list[dict[str, Any]],
    query: str,
    uncertain_ids: set[str],
) -> dict[str, Any] | None:
    payloads = [row["payload"] for row in rows]
    display = entity_display(payloads)
    surfaces: list[dict[str, Any]] = []
    _append_surface(
        surfaces,
        display.get("name"),
        query,
        field="display.name",
        exact_rank=0,
    )
    for row in rows:
        payload = row["payload"]
        common = {
            "bundle": row["bundle"],
            "ref": row["ref"],
            "source_title": row["source_title"],
        }
        _append_surface(
            surfaces,
            payload.get("canonical_name"),
            query,
            field="entity.canonical_name",
            exact_rank=1,
            **common,
        )
        for alias in payload.get("aliases") or []:
            _append_surface(
                surfaces,
                alias,
                query,
                field="entity.alias",
                exact_rank=1,
                **common,
            )
        for mention in payload.get("mentions") or []:
            if isinstance(mention, dict):
                _append_surface(
                    surfaces,
                    mention.get("text"),
                    query,
                    field="entity.mention",
                    exact_rank=4,
                    secondary=True,
                    **common,
                )
        _append_surface(
            surfaces,
            payload.get("description"),
            query,
            field="entity.description",
            exact_rank=4,
            secondary=True,
            **common,
        )

    matches = _dedupe_surfaces(surfaces)
    if not matches:
        return None
    return {
        "kind": "entity",
        "canonical_id": canonical_id,
        "display": display,
        "representation_count": len(rows),
        "source_count": len({row["bundle"] for row in rows}),
        "source_titles": sorted({row["source_title"] for row in rows}),
        "identity_uncertain": canonical_id in uncertain_ids,
        "navigation_path": f"/entities/{canonical_id}",
        "match": {
            "rank": matches[0]["rank"],
            "matched_surfaces": matches[:12],
        },
    }


def _event_result(canonical_id: str, rows: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
    payloads = [row["payload"] for row in rows]
    display = event_display(payloads)
    surfaces: list[dict[str, Any]] = []
    _append_surface(
        surfaces,
        display.get("title"),
        query,
        field="display.title",
        exact_rank=0,
    )
    for row in rows:
        payload = row["payload"]
        common = {
            "bundle": row["bundle"],
            "ref": row["ref"],
            "source_title": row["source_title"],
        }
        _append_surface(
            surfaces,
            payload.get("title"),
            query,
            field="event.title",
            exact_rank=1,
            **common,
        )
        _append_surface(
            surfaces,
            payload.get("summary"),
            query,
            field="event.summary",
            exact_rank=4,
            secondary=True,
            **common,
        )
        time = payload.get("time")
        if isinstance(time, dict):
            _append_surface(
                surfaces,
                time.get("original_text"),
                query,
                field="event.time.original_text",
                exact_rank=4,
                secondary=True,
                **common,
            )
            normalized = time.get("normalized")
            if isinstance(normalized, dict) and isinstance(normalized.get("year"), int):
                _append_surface(
                    surfaces,
                    str(normalized["year"]),
                    query,
                    field="event.time.year",
                    exact_rank=4,
                    secondary=True,
                    **common,
                )

    matches = _dedupe_surfaces(surfaces)
    if not matches:
        return None
    return {
        "kind": "event",
        "canonical_id": canonical_id,
        "display": display,
        "time": time_window(payloads),
        "representation_count": len(rows),
        "source_count": len({row["bundle"] for row in rows}),
        "source_titles": sorted({row["source_title"] for row in rows}),
        "navigation_path": f"/events/{canonical_id}",
        "match": {
            "rank": matches[0]["rank"],
            "matched_surfaces": matches[:12],
        },
    }


def search_catalog(
    conn,
    *,
    q: str,
    kind: str = "all",
    limit: int = 20,
) -> dict[str, Any]:
    query = _query_text(q)
    if kind not in VALID_KINDS:
        raise ReadModelError("kind must be one of all, entity, event")
    if not isinstance(limit, int) or limit < 1 or limit > MAX_SEARCH_LIMIT:
        raise ReadModelError(f"limit must be between 1 and {MAX_SEARCH_LIMIT}")

    items: list[dict[str, Any]] = []
    if kind in {"all", "entity"}:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in _rows(conn, "entity"):
            grouped[row["canonical_id"]].append(row)
        uncertain_ids = _uncertain_entity_ids(conn)
        for canonical_id, rows in grouped.items():
            result = _entity_result(canonical_id, rows, query, uncertain_ids)
            if result is not None:
                items.append(result)

    if kind in {"all", "event"}:
        grouped = defaultdict(list)
        for row in _rows(conn, "event"):
            grouped[row["canonical_id"]].append(row)
        for canonical_id, rows in grouped.items():
            result = _event_result(canonical_id, rows, query)
            if result is not None:
                items.append(result)

    def sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
        label = item["display"].get("name") if item["kind"] == "entity" else item["display"].get("title")
        return (
            item["match"]["rank"],
            0 if item["kind"] == "entity" else 1,
            (label or "").casefold(),
            item["canonical_id"],
        )

    items.sort(key=sort_key)
    total = len(items)
    page = items[:limit]
    return {
        "schema": "chronicle.search",
        "version": READ_SCHEMA_VERSION,
        "query": {"q": query, "kind": kind, "limit": limit},
        "page": {
            "total": total,
            "returned": len(page),
            "has_more": total > len(page),
        },
        "items": page,
    }
