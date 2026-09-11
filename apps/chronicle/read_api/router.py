"""Framework-free routing for Chronicle read-model HTTP contracts."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from coverage import build_coverage
from historical_moment import build_historical_moment
from read_common import ReadModelError, ReadModelNotFound
from reader_chapters import CHAPTERS_PREFIX, dispatch_chapters
from reader_presentation import latest_reader_presentation
from reader_streams import (
    ReadingStreamBadRequest,
    ReadingStreamError,
    ReadingStreamNotFound,
    list_streams,
    locate_unit,
    stream_detail,
    stream_groups,
    stream_units,
)
from reading_events import (
    ReadModelInconsistency,
    event_preview,
    event_targets,
)
from search import search_catalog


def _single(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if not values:
        return None
    if len(values) != 1:
        raise ReadModelError(f"query parameter {name} must appear once")
    return values[0]


def _optional_int(query: dict[str, list[str]], name: str) -> int | None:
    value = _single(query, name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ReadModelError(f"query parameter {name} must be an integer") from exc


def _scalar_query(raw_query: str, allowed: set[str]) -> dict[str, str]:
    """Parse a query string, rejecting unknown or repeated parameters.

    The reading contracts bind identity and pagination to the query
    (``catalog``/``stream``/``cursor``), so an unexpected or duplicated
    parameter is a 400 rather than a silently ignored value.
    """
    query = parse_qs(raw_query, keep_blank_values=True)
    unknown = sorted(set(query) - allowed)
    if unknown:
        raise ReadModelError(f"unknown query parameter(s): {', '.join(unknown)}")
    scalars: dict[str, str] = {}
    for name, values in query.items():
        if len(values) != 1:
            raise ReadModelError(f"query parameter {name} must appear once")
        scalars[name] = values[0]
    return scalars


def _int_param(query: dict[str, str], name: str, default: int) -> int:
    if name not in query:
        return default
    try:
        return int(query[name])
    except (TypeError, ValueError) as exc:
        raise ReadModelError(f"query parameter {name} must be an integer") from exc


def _error(status: int, code: str, message: str) -> tuple[int, dict[str, Any]]:
    return status, {
        "schema": "chronicle.error",
        "version": "0.1",
        "error": {"code": code, "message": message},
    }


def _with_reader_presentation(repo, *, target_kind: str, canonical_id: str, detail: dict[str, Any]) -> dict[str, Any]:
    """Overlay the latest derived reader projection without changing authority."""
    enriched = dict(detail)
    enriched["reader_presentation"] = latest_reader_presentation(
        repo.conn, target_kind=target_kind, canonical_id=canonical_id
    )
    return enriched


def _scoped_detail(detail: dict[str, Any]) -> dict[str, Any]:
    """Return a snapshot-scoped Event/Entity detail without a later overlay.

    A Reader Presentation has no snapshot binding, so the "latest published"
    projection cannot be proven to belong to the requested catalog. The
    snapshot view therefore carries source-owned evidence only and reports
    ``reader_presentation: null`` instead of mixing in later content.
    """
    scoped = dict(detail)
    scoped["reader_presentation"] = None
    return scoped


def _reading_streams(repo, path: str, raw_query: str) -> tuple[int, dict[str, Any]] | None:
    prefix = "/v0/reading-streams"
    if path == prefix:
        query = _scalar_query(raw_query, {"catalog", "limit", "cursor"})
        payload = list_streams(
            repo.conn,
            catalog_sha=query.get("catalog"),
            limit=_int_param(query, "limit", 20),
            cursor=query.get("cursor"),
        )
        return 200, payload
    if not path.startswith(prefix + "/"):
        return None
    parts = path[len(prefix) + 1:].split("/")
    stream_id = parts[0]
    if len(parts) == 1 and stream_id:
        query = _scalar_query(raw_query, {"catalog"})
        return 200, stream_detail(
            repo.conn, stream_id=stream_id, catalog_sha=query.get("catalog")
        )
    if len(parts) == 2 and stream_id and parts[1] == "units":
        query = _scalar_query(raw_query, {"catalog", "limit", "cursor", "direction"})
        return 200, stream_units(
            repo.conn,
            stream_id=stream_id,
            catalog_sha=query.get("catalog"),
            limit=_int_param(query, "limit", 20),
            cursor=query.get("cursor"),
            direction=query.get("direction"),
        )
    if len(parts) == 2 and stream_id and parts[1] == "groups":
        query = _scalar_query(raw_query, {"catalog", "limit", "cursor", "direction"})
        return 200, stream_groups(
            repo.conn,
            stream_id=stream_id,
            catalog_sha=query.get("catalog"),
            limit=_int_param(query, "limit", 50),
            cursor=query.get("cursor"),
            direction=query.get("direction"),
        )
    if len(parts) == 2 and stream_id and parts[1] == "locate":
        query = _scalar_query(raw_query, {"catalog", "unit_id", "limit"})
        unit_id = query.get("unit_id")
        if not unit_id:
            raise ReadModelError("query parameter unit_id is required")
        return 200, locate_unit(
            repo.conn,
            stream_id=stream_id,
            unit_id=unit_id,
            catalog_sha=query.get("catalog"),
            limit=_int_param(query, "limit", 20),
        )
    return _error(404, "not_found", "route not found")


def _reading_events(repo, path: str, raw_query: str) -> tuple[int, dict[str, Any]] | None:
    prefix = "/v0/reading-events/"
    if not path.startswith(prefix) or len(path) <= len(prefix):
        return None
    parts = path[len(prefix):].split("/")
    if len(parts) != 2 or not parts[0] or parts[1] not in ("preview", "targets"):
        return _error(404, "not_found", "route not found")
    event_id, action = parts
    if action == "preview":
        query = _scalar_query(raw_query, {"catalog"})
        catalog = query.get("catalog")
        if not catalog:
            raise ReadModelError("query parameter catalog is required")
        return 200, event_preview(
            repo.conn, snapshot_catalog_sha=catalog, canonical_event_id=event_id
        )
    query = _scalar_query(raw_query, {"catalog", "limit", "cursor"})
    catalog = query.get("catalog")
    if not catalog:
        raise ReadModelError("query parameter catalog is required")
    return 200, event_targets(
        repo.conn,
        snapshot_catalog_sha=catalog,
        canonical_event_id=event_id,
        limit=_int_param(query, "limit", 20),
        cursor=query.get("cursor"),
    )


def dispatch(
    repo,
    method: str,
    path: str,
    raw_query: str = "",
    *,
    source_dir=None,
) -> tuple[int, dict[str, Any]]:
    if method != "GET":
        return _error(405, "method_not_allowed", "only GET is supported")

    try:
        if path == "/healthz":
            return 200, {"status": "ok"}

        if path == "/v0/timeline":
            query = parse_qs(raw_query, keep_blank_values=True)
            allowed = {"from_year", "to_year", "limit", "offset"}
            unknown = sorted(set(query) - allowed)
            if unknown:
                raise ReadModelError(f"unknown query parameter(s): {', '.join(unknown)}")
            limit = _optional_int(query, "limit")
            offset = _optional_int(query, "offset")
            return 200, repo.timeline(
                from_year=_optional_int(query, "from_year"),
                to_year=_optional_int(query, "to_year"),
                limit=50 if limit is None else limit,
                offset=0 if offset is None else offset,
            )

        if path == "/v0/coverage":
            query = parse_qs(raw_query, keep_blank_values=True)
            allowed = {"from_year", "to_year"}
            unknown = sorted(set(query) - allowed)
            if unknown:
                raise ReadModelError(f"unknown query parameter(s): {', '.join(unknown)}")
            return 200, build_coverage(
                repo.conn,
                from_year=_optional_int(query, "from_year"),
                to_year=_optional_int(query, "to_year"),
            )

        if path == "/v0/historical-moment":
            query = parse_qs(raw_query, keep_blank_values=True)
            allowed = {"year", "from_year", "to_year", "limit", "offset"}
            unknown = sorted(set(query) - allowed)
            if unknown:
                raise ReadModelError(f"unknown query parameter(s): {', '.join(unknown)}")
            limit = _optional_int(query, "limit")
            offset = _optional_int(query, "offset")
            return 200, build_historical_moment(
                repo.conn,
                year=_optional_int(query, "year"),
                from_year=_optional_int(query, "from_year"),
                to_year=_optional_int(query, "to_year"),
                limit=50 if limit is None else limit,
                offset=0 if offset is None else offset,
            )

        if path == "/v0/search":
            query = parse_qs(raw_query, keep_blank_values=True)
            allowed = {"q", "kind", "limit"}
            unknown = sorted(set(query) - allowed)
            if unknown:
                raise ReadModelError(f"unknown query parameter(s): {', '.join(unknown)}")
            q = _single(query, "q")
            if q is None:
                raise ReadModelError("query parameter q is required")
            kind = _single(query, "kind") or "all"
            limit = _optional_int(query, "limit")
            return 200, search_catalog(
                repo.conn,
                q=q,
                kind=kind,
                limit=20 if limit is None else limit,
            )

        event_prefix = "/v0/events/"
        if path.startswith(event_prefix) and len(path) > len(event_prefix):
            canonical_id = path[len(event_prefix):]
            if "/" in canonical_id:
                return _error(404, "not_found", "route not found")
            query = _scalar_query(raw_query, {"catalog"})
            catalog = query.get("catalog")
            if catalog is None:
                detail = repo.event_detail(canonical_id)
                return 200, _with_reader_presentation(
                    repo,
                    target_kind="event",
                    canonical_id=canonical_id,
                    detail=detail,
                )
            return 200, _scoped_detail(repo.event_detail(canonical_id, catalog_sha=catalog))

        entity_prefix = "/v0/entities/"
        if path.startswith(entity_prefix) and len(path) > len(entity_prefix):
            canonical_id = path[len(entity_prefix):]
            if "/" in canonical_id:
                return _error(404, "not_found", "route not found")
            query = _scalar_query(raw_query, {"catalog"})
            catalog = query.get("catalog")
            if catalog is None:
                detail = repo.entity_detail(canonical_id)
                return 200, _with_reader_presentation(
                    repo,
                    target_kind="entity",
                    canonical_id=canonical_id,
                    detail=detail,
                )
            return 200, _scoped_detail(repo.entity_detail(canonical_id, catalog_sha=catalog))

        reading_streams = _reading_streams(repo, path, raw_query)
        if reading_streams is not None:
            return reading_streams

        reading_events = _reading_events(repo, path, raw_query)
        if reading_events is not None:
            return reading_events

        if path == CHAPTERS_PREFIX or path.startswith(CHAPTERS_PREFIX + "/"):
            # Public chapter directory / full translation / pinned source
            # (C2-R1-T14). Runs in the caller's read-only transaction and
            # reuses the configured storage_dir-injected source reader.
            return dispatch_chapters(
                repo.conn,
                method=method,
                path=path,
                raw_query=raw_query,
                source_dir=source_dir,
            )

        return _error(404, "not_found", "route not found")
    except ReadModelNotFound as exc:
        return _error(404, "not_found", str(exc))
    except ReadModelError as exc:
        return _error(400, "bad_request", str(exc))
    except ReadingStreamNotFound as exc:
        return _error(404, "not_found", str(exc))
    except ReadingStreamBadRequest as exc:
        return _error(400, "bad_request", str(exc))
    except ReadModelInconsistency as exc:
        return _error(500, "internal_error", str(exc))
    except ReadingStreamError as exc:
        return _error(500, "internal_error", str(exc))
