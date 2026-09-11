"""Chronicle C2-R2-T07 continuous-reading public domain queries.

SELECT-only data functions over the T05 reading stream store
(``continuous-reading.md`` sections 5-6) for the frontend reading surface.
There is deliberately no router/HTTP/client wiring here: ``server.py``,
``router.py``, the Rust public boundary and the typed client belong to T09.
The body is never re-authored: text stays in the T05 ``reading_units``
rows compiled from the first-round chapter publications, and source bytes
keep being served by the first-round chapter source reader.

Five queries supply a fixed snapshot and stable coordinates:

- :func:`list_streams` — published stream directory ordered by
  ``document_id / revision_no / stream_id``, one revision per stream;
- :func:`stream_detail` — stream metadata, ordered chapter directory,
  unit/group totals, manifest hash and the starting locator, with no body
  inline;
- :func:`stream_units` — bidirectional bounded body page with
  ``prev_cursor`` / ``next_cursor``, ordinals, group continuation, the
  program-sliced text/event segments and source anchors;
- :func:`stream_groups` — time-axis group page with exact first/last
  locators, in reading order;
- :func:`locate_unit` — the exact target unit, the page that contains it
  and the adjacent group page entry, resolved by indexed ``unit_id`` /
  ordinal, never by walking from the first page.

Every response is an envelope carrying the resolved snapshot and the
echoed query alongside the page::

    {
      "schema": "chronicle.reading-stream-...",
      "version": "0.1",
      "snapshot": {"catalog_sha": "...", "publication_sequence": 7},
      "query": {...},
      "page": {...}
    }

A request without ``catalog_sha`` resolves the newest published catalog
once (by ``publication_sequence``, never by wall-clock time) and pins it in
``snapshot``; later pages must send it back explicitly. A cursor is opaque,
versioned and bound to its scope (directory / units / groups), snapshot
catalog, stream, page direction and last stable ordinal, so a cursor from
another stream, snapshot or direction is a ``bad_request``.

GET paths never write, never allocate canonical IDs and never call a
model. Errors are raised as :class:`ReadingStreamError` subclasses whose
``code`` / ``status`` mirror ``reading_contract.READING_ERROR_CODES`` so the
T09 HTTP layer can map them without re-deriving semantics.
"""

from __future__ import annotations

import base64
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

_PERSISTENCE_DIR = Path(__file__).resolve().parent.parent / "persistence"
if str(_PERSISTENCE_DIR) not in sys.path:
    sys.path.insert(0, str(_PERSISTENCE_DIR))

import canonical_store as _canonical_store  # noqa: E402
import reading_contract as _reading_contract  # noqa: E402
import reading_store as _reading_store  # noqa: E402
from common import (  # noqa: E402
    PersistenceError,
    canonical_json_bytes,
)

_READING_VERSION = "0.1"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

_LIST_SCHEMA = "chronicle.reading-stream-directory"
_DETAIL_SCHEMA = "chronicle.reading-stream-detail"
_UNITS_SCHEMA = "chronicle.reading-stream-units"
_GROUPS_SCHEMA = "chronicle.reading-stream-groups"
_LOCATE_SCHEMA = "chronicle.reading-stream-locate"

_CURSOR_VERSION = 1
_UNIT_CURSOR_SCOPE = "reading-units"
_GROUP_CURSOR_SCOPE = "reading-groups"
_DIRECTORY_CURSOR_SCOPE = "reading-stream-directory"

_LIMITS = _reading_contract.ReadingLimits()
_CURSOR_MARGIN_BYTES = 1024


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ReadingStreamError(RuntimeError):
    """Base error for the continuous-reading domain queries."""

    code = "internal"
    status = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ReadingStreamBadRequest(ReadingStreamError):
    """Invalid parameters or a cursor bound to another scope/snapshot."""

    code = "bad_request"
    status = 400


class ReadingStreamNotFound(ReadingStreamError):
    """Unknown or snapshot-invisible stream/unit."""

    code = "not_found"
    status = 404


# ---------------------------------------------------------------------------
# Opaque cursors (versioned, scope- and snapshot-bound)
# ---------------------------------------------------------------------------


def _b64encode(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(raw: str, *, what: str) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw:
        raise ReadingStreamBadRequest(f"{what} cursor must be a non-empty string")
    try:
        padded = raw + ("=" * (-len(raw) % 4))
        payload = json.loads(
            base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        )
    except (ValueError, UnicodeDecodeError) as exc:
        raise ReadingStreamBadRequest(f"{what} cursor is not valid: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReadingStreamBadRequest(f"{what} cursor is not valid")
    return payload


def _cursor_ordinal(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ReadingStreamBadRequest("cursor carries an invalid ordinal")
    return int(value)


def encode_unit_cursor(
    *, kind: str, stream_id: str, catalog_sha: str, ordinal: int
) -> str:
    """Encode a forward (``next``) or backward (``prev``) body cursor."""
    if kind not in ("next", "prev"):
        raise ReadingStreamBadRequest("unit cursor kind must be next or prev")
    return _b64encode(
        {
            "v": _CURSOR_VERSION,
            "scope": _UNIT_CURSOR_SCOPE,
            "kind": kind,
            "stream_id": str(stream_id),
            "catalog_sha": str(catalog_sha),
            "ordinal": int(ordinal),
        }
    )


def decode_unit_cursor(
    raw: str,
    *,
    stream_id: str,
    catalog_sha: str,
    expected_kind: str | None = None,
) -> dict[str, Any]:
    """Decode and scope-check a body cursor.

    ``expected_kind`` rejects a cursor from the other direction when the
    caller already committed to one.
    """
    payload = _b64decode(raw, what="reading units")
    if payload.get("v") != _CURSOR_VERSION:
        raise ReadingStreamBadRequest("reading units cursor version is not supported")
    if payload.get("scope") != _UNIT_CURSOR_SCOPE:
        raise ReadingStreamBadRequest("reading units cursor belongs to a different scope")
    if str(payload.get("stream_id") or "") != str(stream_id):
        raise ReadingStreamBadRequest("reading units cursor belongs to a different stream")
    if str(payload.get("catalog_sha") or "") != str(catalog_sha):
        raise ReadingStreamBadRequest("reading units cursor belongs to a different snapshot")
    kind = payload.get("kind")
    if kind not in ("next", "prev"):
        raise ReadingStreamBadRequest("reading units cursor carries an invalid direction")
    if expected_kind is not None and kind != expected_kind:
        raise ReadingStreamBadRequest("reading units cursor direction does not match")
    return {"kind": kind, "ordinal": _cursor_ordinal(payload.get("ordinal"))}


def encode_group_cursor(
    *, kind: str, stream_id: str, catalog_sha: str, ordinal: int
) -> str:
    """Encode a group-axis cursor.

    ``next`` / ``prev`` walk in reading order; ``at`` starts a forward page
    at the named group (the locate entry into the axis).
    """
    if kind not in ("next", "prev", "at"):
        raise ReadingStreamBadRequest("group cursor kind must be next, prev or at")
    return _b64encode(
        {
            "v": _CURSOR_VERSION,
            "scope": _GROUP_CURSOR_SCOPE,
            "kind": kind,
            "stream_id": str(stream_id),
            "catalog_sha": str(catalog_sha),
            "ordinal": int(ordinal),
        }
    )


def decode_group_cursor(
    raw: str,
    *,
    stream_id: str,
    catalog_sha: str,
    expected_kind: str | None = None,
) -> dict[str, Any]:
    payload = _b64decode(raw, what="reading groups")
    if payload.get("v") != _CURSOR_VERSION:
        raise ReadingStreamBadRequest("reading groups cursor version is not supported")
    if payload.get("scope") != _GROUP_CURSOR_SCOPE:
        raise ReadingStreamBadRequest("reading groups cursor belongs to a different scope")
    if str(payload.get("stream_id") or "") != str(stream_id):
        raise ReadingStreamBadRequest("reading groups cursor belongs to a different stream")
    if str(payload.get("catalog_sha") or "") != str(catalog_sha):
        raise ReadingStreamBadRequest("reading groups cursor belongs to a different snapshot")
    kind = payload.get("kind")
    if kind not in ("next", "prev", "at"):
        raise ReadingStreamBadRequest("reading groups cursor carries an invalid direction")
    if expected_kind is not None and kind != expected_kind:
        raise ReadingStreamBadRequest("reading groups cursor direction does not match")
    return {"kind": kind, "ordinal": _cursor_ordinal(payload.get("ordinal"))}


def _encode_directory_cursor(*, catalog_sha: str, offset: int) -> str:
    return _b64encode(
        {
            "v": _CURSOR_VERSION,
            "scope": _DIRECTORY_CURSOR_SCOPE,
            "catalog_sha": str(catalog_sha),
            "offset": int(offset),
        }
    )


def _decode_directory_cursor(raw: str, *, catalog_sha: str) -> int:
    payload = _b64decode(raw, what="reading stream directory")
    if payload.get("v") != _CURSOR_VERSION:
        raise ReadingStreamBadRequest("directory cursor version is not supported")
    if payload.get("scope") != _DIRECTORY_CURSOR_SCOPE:
        raise ReadingStreamBadRequest("directory cursor belongs to a different scope")
    if str(payload.get("catalog_sha") or "") != str(catalog_sha):
        raise ReadingStreamBadRequest("directory cursor belongs to a different snapshot")
    return _cursor_ordinal(payload.get("offset"))


# ---------------------------------------------------------------------------
# Snapshot resolution and shared validation
# ---------------------------------------------------------------------------


def _require_sha(value: Any, what: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.match(value):
        raise ReadingStreamBadRequest(f"{what} must be a lowercase hex SHA-256 string")
    return value


def _require_stream_uuid(value: Any) -> uuid.UUID:
    try:
        parsed = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ReadingStreamBadRequest(f"stream_id must be a UUID: {value!r}") from exc
    if parsed.version != 7:
        raise ReadingStreamBadRequest("stream_id must be a UUIDv7")
    return parsed


def _validate_limit(value: Any, *, maximum: int, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > maximum:
        raise ReadingStreamBadRequest(f"{what} must be an integer between 1 and {maximum}")
    return int(value)


def resolve_snapshot(conn, catalog_sha: str | None = None) -> dict[str, Any]:
    """Resolve the exploration snapshot, defaulting to the newest catalog.

    The newest catalog is the one with the highest ``publication_sequence``
    (never transaction time). The returned ``catalog_sha`` is what later
    pages must send back; a missing catalog is an explicit 404 rather than a
    silent fallback to another snapshot.
    """
    if catalog_sha is None:
        latest = _canonical_store.read_latest_catalog_sha256(conn)
        if latest is None:
            raise ReadingStreamNotFound("no published canonical catalog is available")
        catalog_sha = latest
    else:
        catalog_sha = _require_sha(catalog_sha, "catalog")
    row = conn.execute(
        "SELECT publication_sequence FROM chronicle.canonical_catalogs"
        " WHERE artifact_sha256 = %s",
        (catalog_sha,),
    ).fetchone()
    if row is None:
        raise ReadingStreamNotFound(f"unknown catalog {catalog_sha}")
    return {"catalog_sha": catalog_sha, "publication_sequence": int(row[0])}


def _envelope(
    *, schema: str, snapshot: dict[str, Any], query: dict[str, Any], page: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema": schema,
        "version": _READING_VERSION,
        "snapshot": {
            "catalog_sha": snapshot["catalog_sha"],
            "publication_sequence": snapshot["publication_sequence"],
        },
        "query": query,
        "page": page,
    }


def _require_visible_stream(
    conn, *, stream_id: uuid.UUID, snapshot: dict[str, Any]
) -> None:
    """Fail closed when the stream is unknown or outside the snapshot."""
    row = conn.execute(
        """
        SELECT s.origin_catalog_sha, origin.publication_sequence
        FROM chronicle.reading_streams s
        JOIN chronicle.canonical_catalogs origin
          ON origin.artifact_sha256 = s.origin_catalog_sha
        WHERE s.stream_id = %s
        """,
        (stream_id,),
    ).fetchone()
    if row is None:
        raise ReadingStreamNotFound(f"unknown reading stream {stream_id}")
    if int(row[1]) > snapshot["publication_sequence"]:
        raise ReadingStreamNotFound(
            f"reading stream {stream_id} is not visible in snapshot "
            f"{snapshot['catalog_sha']}"
        )


def _read_stream_metadata(conn, *, stream_id: uuid.UUID, catalog_sha: str) -> dict[str, Any]:
    try:
        return _reading_store.read_reading_stream(
            conn, stream_id=stream_id, snapshot_catalog_sha=catalog_sha
        )
    except PersistenceError as exc:  # pragma: no cover - pre-check already ran
        raise ReadingStreamNotFound(str(exc)) from exc


def _unit_dto(
    unit: dict[str, Any], *, stream_id: str, catalog_sha: str
) -> dict[str, Any]:
    return {
        "unit_id": unit["unit_id"],
        "ordinal": unit["ordinal"],
        "stream_id": stream_id,
        "catalog_sha": catalog_sha,
        "publication_id": unit["publication_id"],
        "chapter_id": unit["chapter_id"],
        "block_id": unit["block_id"],
        "artifact_sha256": unit["artifact_sha256"],
        "text_hash": unit["text_hash"],
        "source_anchor_ids": unit["source_anchor_ids"],
        "segments": unit["segments"],
        "narrative_time": unit["narrative_time"],
        "context_entities": unit["context_entities"],
        "group_id": unit["group_id"],
        "continues_previous": unit["continues_previous"],
    }


def _page_bytes(page: dict[str, Any]) -> int:
    return len(canonical_json_bytes(page))


# ---------------------------------------------------------------------------
# list_streams
# ---------------------------------------------------------------------------


def list_streams(
    conn,
    *,
    catalog_sha: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List the streams visible in one snapshot in stable directory order."""
    limit = _validate_limit(limit, maximum=100, what="limit")
    snapshot = resolve_snapshot(conn, catalog_sha)
    catalog = snapshot["catalog_sha"]
    offset = 0
    if cursor is not None:
        offset = _decode_directory_cursor(cursor, catalog_sha=catalog)
    result = _reading_store.list_reading_streams(
        conn, snapshot_catalog_sha=catalog, limit=limit, offset=offset
    )
    items = result["items"]
    has_more = bool(result["has_more"])
    next_cursor = (
        _encode_directory_cursor(catalog_sha=catalog, offset=offset + len(items))
        if has_more and items
        else None
    )
    page = {
        "streams": items,
        "limit": limit,
        "has_more": has_more,
        "next_cursor": next_cursor,
    }
    return _envelope(
        schema=_LIST_SCHEMA,
        snapshot=snapshot,
        query={"limit": limit, "cursor": cursor, "catalog_sha": catalog},
        page=page,
    )


# ---------------------------------------------------------------------------
# stream_detail
# ---------------------------------------------------------------------------


def _chapter_directory(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    chapters = manifest.get("chapters")
    if not isinstance(chapters, list):
        return []
    directory: list[dict[str, Any]] = []
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        directory.append(
            {
                "chapter_id": chapter.get("chapter_id"),
                "chapter_index": chapter.get("chapter_index"),
                "publication_id": chapter.get("publication_id"),
                "artifact_sha256": chapter.get("artifact_sha256"),
                "unit_count": chapter.get("unit_count"),
                "title": chapter.get("title"),
            }
        )
    return directory


def stream_detail(
    conn, *, stream_id: Any, catalog_sha: str | None = None
) -> dict[str, Any]:
    """Return one stream's metadata and chapter directory without body text."""
    stream_uuid = _require_stream_uuid(stream_id)
    snapshot = resolve_snapshot(conn, catalog_sha)
    catalog = snapshot["catalog_sha"]
    _require_visible_stream(conn, stream_id=stream_uuid, snapshot=snapshot)
    metadata = _read_stream_metadata(conn, stream_id=stream_uuid, catalog_sha=catalog)
    manifest = metadata["manifest"] if isinstance(metadata.get("manifest"), dict) else {}

    first_page = _reading_store.read_reading_units(
        conn, stream_id=stream_uuid, limit=1, snapshot_catalog_sha=catalog
    )
    first_units = first_page["items"]
    start_locator = (
        {
            "stream_id": str(stream_uuid),
            "catalog_sha": catalog,
            "unit_id": first_units[0]["unit_id"],
        }
        if first_units
        else None
    )
    page = {
        "stream_id": str(stream_uuid),
        "document_id": metadata["document_id"],
        "revision_id": metadata["revision_id"],
        "revision_no": metadata["revision_no"],
        "catalog_sha": catalog,
        "origin_catalog_sha": metadata["origin_catalog_sha"],
        "manifest_sha": metadata["manifest_sha"],
        "unit_count": metadata["unit_count"],
        "group_count": metadata["group_count"],
        "title": manifest.get("source_title"),
        "full_text_sha256": manifest.get("full_text_sha256"),
        "chapters": _chapter_directory(manifest),
        "start_locator": start_locator,
    }
    return _envelope(
        schema=_DETAIL_SCHEMA,
        snapshot=snapshot,
        query={"catalog_sha": catalog, "stream_id": str(stream_uuid)},
        page=page,
    )


# ---------------------------------------------------------------------------
# stream_units
# ---------------------------------------------------------------------------


def _finalize_unit_page(
    dtos: list[dict[str, Any]],
    *,
    stream_id: str,
    catalog_sha: str,
    limit: int,
    unit_count: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach cursors/continuation and enforce the 2 MiB page budget.

    ``extra`` fields (the locate metadata) are merged into every candidate
    page before its serialized size is measured, so the *final* payload the
    caller serializes — not just the bare unit list — stays within
    ``page_max_bytes``. Units are dropped whole from the tail until it fits;
    a unit is never truncated and the first unit is always kept.
    """
    extra_fields = dict(extra or {})
    while True:
        if dtos:
            first_ordinal = dtos[0]["ordinal"]
            last_ordinal = dtos[-1]["ordinal"]
        else:
            first_ordinal = None
            last_ordinal = None
        has_previous = first_ordinal is not None and first_ordinal > 0
        has_next = last_ordinal is not None and last_ordinal + 1 < unit_count
        page = {
            "stream_id": stream_id,
            "catalog_sha": catalog_sha,
            "limit": limit,
            "units": dtos,
            "prev_cursor": (
                encode_unit_cursor(
                    kind="prev",
                    stream_id=stream_id,
                    catalog_sha=catalog_sha,
                    ordinal=first_ordinal,
                )
                if has_previous
                else None
            ),
            "next_cursor": (
                encode_unit_cursor(
                    kind="next",
                    stream_id=stream_id,
                    catalog_sha=catalog_sha,
                    ordinal=last_ordinal,
                )
                if has_next
                else None
            ),
            "has_previous": has_previous,
            "has_next": has_next,
            "group_continuation": (
                {
                    "group_id": dtos[0]["group_id"],
                    "continues_previous": dtos[0]["continues_previous"],
                }
                if dtos
                else None
            ),
        }
        page.update(extra_fields)
        if len(dtos) <= 1 or _page_bytes(page) <= _LIMITS.page_max_bytes:
            return page
        dtos.pop()


def _build_unit_page(
    conn,
    *,
    stream_id: uuid.UUID,
    catalog_sha: str,
    unit_count: int,
    limit: int,
    after_ordinal: int | None = None,
    before_ordinal: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    page_result = _reading_store.read_reading_units(
        conn,
        stream_id=stream_id,
        limit=limit,
        after_ordinal=after_ordinal,
        before_ordinal=before_ordinal,
        snapshot_catalog_sha=catalog_sha,
    )
    dtos: list[dict[str, Any]] = []
    used = 0
    overhead = _CURSOR_MARGIN_BYTES + (
        _page_bytes(extra) if extra else 0
    )
    budget = _LIMITS.page_max_bytes - overhead
    for unit in page_result["items"]:
        dto = _unit_dto(unit, stream_id=str(stream_id), catalog_sha=catalog_sha)
        size = len(canonical_json_bytes(dto))
        if dtos and used + size > budget:
            break
        dtos.append(dto)
        used += size
    return _finalize_unit_page(
        dtos,
        stream_id=str(stream_id),
        catalog_sha=catalog_sha,
        limit=limit,
        unit_count=unit_count,
        extra=extra,
    )


def stream_units(
    conn,
    *,
    stream_id: Any,
    catalog_sha: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
    direction: str | None = None,
) -> dict[str, Any]:
    """Return a bounded, direction-bound body page for one stream."""
    stream_uuid = _require_stream_uuid(stream_id)
    limit = _validate_limit(limit, maximum=_LIMITS.page_max_limit, what="limit")
    if direction is not None and direction not in ("forward", "backward"):
        raise ReadingStreamBadRequest("direction must be forward or backward")
    snapshot = resolve_snapshot(conn, catalog_sha)
    catalog = snapshot["catalog_sha"]
    _require_visible_stream(conn, stream_id=stream_uuid, snapshot=snapshot)
    metadata = _read_stream_metadata(conn, stream_id=stream_uuid, catalog_sha=catalog)
    unit_count = metadata["unit_count"]

    after_ordinal: int | None = None
    before_ordinal: int | None = None
    if cursor is not None:
        decoded = decode_unit_cursor(cursor, stream_id=str(stream_uuid), catalog_sha=catalog)
        expected = {"forward": "next", "backward": "prev"}.get(direction or "")
        if expected is not None and decoded["kind"] != expected:
            raise ReadingStreamBadRequest(
                "reading units cursor direction does not match the request"
            )
        if decoded["kind"] == "next":
            after_ordinal = decoded["ordinal"]
        else:
            before_ordinal = decoded["ordinal"]
    elif direction == "backward":
        before_ordinal = unit_count

    page = _build_unit_page(
        conn,
        stream_id=stream_uuid,
        catalog_sha=catalog,
        unit_count=unit_count,
        limit=limit,
        after_ordinal=after_ordinal,
        before_ordinal=before_ordinal,
    )
    return _envelope(
        schema=_UNITS_SCHEMA,
        snapshot=snapshot,
        query={
            "catalog_sha": catalog,
            "stream_id": str(stream_uuid),
            "limit": limit,
            "cursor": cursor,
            "direction": direction,
        },
        page=page,
    )


# ---------------------------------------------------------------------------
# stream_groups
# ---------------------------------------------------------------------------


def _group_dto(
    group: dict[str, Any], *, stream_id: str, catalog_sha: str
) -> dict[str, Any]:
    return {
        "group_id": group["group_id"],
        "ordinal": group["ordinal"],
        "year_key": group["year_key"],
        "period_key": group["period_key"],
        "year_label": group["year_label"],
        "period_label": group["period_label"],
        "precision": group["precision"],
        "observations": group["observations"],
        "continues_previous": group["continues_previous"],
        "first_locator": {
            "stream_id": stream_id,
            "catalog_sha": catalog_sha,
            "unit_id": group["first_unit_id"],
        },
        "last_locator": {
            "stream_id": stream_id,
            "catalog_sha": catalog_sha,
            "unit_id": group["last_unit_id"],
        },
        "unit_count": group["unit_count"],
    }


def stream_groups(
    conn,
    *,
    stream_id: Any,
    catalog_sha: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    direction: str | None = None,
) -> dict[str, Any]:
    """Return a bounded time-axis group page with exact first/last locators."""
    stream_uuid = _require_stream_uuid(stream_id)
    limit = _validate_limit(limit, maximum=_LIMITS.group_max_limit, what="limit")
    if direction is not None and direction not in ("forward", "backward"):
        raise ReadingStreamBadRequest("direction must be forward or backward")
    snapshot = resolve_snapshot(conn, catalog_sha)
    catalog = snapshot["catalog_sha"]
    _require_visible_stream(conn, stream_id=stream_uuid, snapshot=snapshot)
    metadata = _read_stream_metadata(conn, stream_id=stream_uuid, catalog_sha=catalog)
    group_count = metadata["group_count"]

    after_group: int | None = None
    before_group: int | None = None
    if cursor is not None:
        decoded = decode_group_cursor(cursor, stream_id=str(stream_uuid), catalog_sha=catalog)
        expected = {"forward": "next", "backward": "prev"}.get(direction or "")
        if expected is not None and decoded["kind"] != expected:
            raise ReadingStreamBadRequest(
                "reading groups cursor direction does not match the request"
            )
        if decoded["kind"] == "next":
            after_group = decoded["ordinal"]
        elif decoded["kind"] == "prev":
            before_group = decoded["ordinal"]
        else:  # "at": start a forward page at the named group
            after_group = decoded["ordinal"] - 1 if decoded["ordinal"] > 0 else None
    elif direction == "backward":
        before_group = group_count

    result = _reading_store.read_reading_groups(
        conn,
        stream_id=stream_uuid,
        limit=limit,
        after_group_ordinal=after_group,
        before_group_ordinal=before_group,
        snapshot_catalog_sha=catalog,
    )
    groups = [
        _group_dto(group, stream_id=str(stream_uuid), catalog_sha=catalog)
        for group in result["items"]
    ]
    if groups:
        first_ordinal = groups[0]["ordinal"]
        last_ordinal = groups[-1]["ordinal"]
    else:
        first_ordinal = last_ordinal = None
    has_previous = first_ordinal is not None and first_ordinal > 0
    has_next = last_ordinal is not None and last_ordinal + 1 < group_count
    page = {
        "stream_id": str(stream_uuid),
        "catalog_sha": catalog,
        "limit": limit,
        "groups": groups,
        "prev_cursor": (
            encode_group_cursor(
                kind="prev",
                stream_id=str(stream_uuid),
                catalog_sha=catalog,
                ordinal=first_ordinal,
            )
            if has_previous
            else None
        ),
        "next_cursor": (
            encode_group_cursor(
                kind="next",
                stream_id=str(stream_uuid),
                catalog_sha=catalog,
                ordinal=last_ordinal,
            )
            if has_next
            else None
        ),
        "has_previous": has_previous,
        "has_next": has_next,
    }
    return _envelope(
        schema=_GROUPS_SCHEMA,
        snapshot=snapshot,
        query={
            "catalog_sha": catalog,
            "stream_id": str(stream_uuid),
            "limit": limit,
            "cursor": cursor,
            "direction": direction,
        },
        page=page,
    )


# ---------------------------------------------------------------------------
# locate_unit
# ---------------------------------------------------------------------------


def locate_unit(
    conn,
    *,
    stream_id: Any,
    unit_id: str,
    catalog_sha: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Locate one exact unit by indexed key without walking the stream.

    The returned page starts at the target ordinal and the ``group_cursor``
    opens the time-axis page covering the target's group.
    """
    stream_uuid = _require_stream_uuid(stream_id)
    if not isinstance(unit_id, str) or not unit_id:
        raise ReadingStreamBadRequest("unit_id must be a non-empty string")
    limit = _validate_limit(limit, maximum=_LIMITS.page_max_limit, what="limit")
    snapshot = resolve_snapshot(conn, catalog_sha)
    catalog = snapshot["catalog_sha"]
    _require_visible_stream(conn, stream_id=stream_uuid, snapshot=snapshot)
    metadata = _read_stream_metadata(conn, stream_id=stream_uuid, catalog_sha=catalog)

    try:
        target = _reading_store.read_reading_unit(
            conn, stream_id=stream_uuid, unit_id=unit_id, snapshot_catalog_sha=catalog
        )
    except PersistenceError as exc:
        raise ReadingStreamNotFound(str(exc)) from exc

    ordinal = target["ordinal"]

    group_row = conn.execute(
        """
        SELECT ordinal FROM chronicle.reading_time_groups
        WHERE stream_id = %s AND group_id = %s
        """,
        (stream_uuid, target["group_id"]),
    ).fetchone()
    if group_row is None:  # pragma: no cover - store guarantees a group
        raise ReadingStreamError(
            f"reading unit {unit_id} has no time group in stream {stream_uuid}"
        )
    group_ordinal = int(group_row[0])
    # Locate metadata is folded into the page *before* the 2 MiB budget is
    # applied, so the final serialized payload stays within the page cap.
    # The target itself is page["units"][0] (and locator); it is deliberately
    # not duplicated as a second full copy.
    locate_meta = {
        "locator": {
            "stream_id": str(stream_uuid),
            "catalog_sha": catalog,
            "unit_id": unit_id,
        },
        "target_ordinal": ordinal,
        "group_id": target["group_id"],
        "group_ordinal": group_ordinal,
        "group_cursor": encode_group_cursor(
            kind="at",
            stream_id=str(stream_uuid),
            catalog_sha=catalog,
            ordinal=group_ordinal,
        ),
    }
    page = _build_unit_page(
        conn,
        stream_id=stream_uuid,
        catalog_sha=catalog,
        unit_count=metadata["unit_count"],
        limit=limit,
        after_ordinal=ordinal - 1 if ordinal > 0 else None,
        extra=locate_meta,
    )
    return _envelope(
        schema=_LOCATE_SCHEMA,
        snapshot=snapshot,
        query={
            "catalog_sha": catalog,
            "stream_id": str(stream_uuid),
            "unit_id": unit_id,
            "limit": limit,
        },
        page=page,
    )


__all__ = [
    "ReadingStreamBadRequest",
    "ReadingStreamError",
    "ReadingStreamNotFound",
    "decode_group_cursor",
    "decode_unit_cursor",
    "encode_group_cursor",
    "encode_unit_cursor",
    "list_streams",
    "locate_unit",
    "resolve_snapshot",
    "stream_detail",
    "stream_groups",
    "stream_units",
]
