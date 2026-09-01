"""Framework-free routing for Chronicle read-model HTTP contracts."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from read_common import ReadModelError, ReadModelNotFound


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


def _error(status: int, code: str, message: str) -> tuple[int, dict[str, Any]]:
    return status, {
        "schema": "chronicle.error",
        "version": "0.1",
        "error": {"code": code, "message": message},
    }


def dispatch(repo, method: str, path: str, raw_query: str = "") -> tuple[int, dict[str, Any]]:
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

        event_prefix = "/v0/events/"
        if path.startswith(event_prefix) and len(path) > len(event_prefix):
            canonical_id = path[len(event_prefix):]
            if "/" in canonical_id:
                return _error(404, "not_found", "route not found")
            return 200, repo.event_detail(canonical_id)

        entity_prefix = "/v0/entities/"
        if path.startswith(entity_prefix) and len(path) > len(entity_prefix):
            canonical_id = path[len(entity_prefix):]
            if "/" in canonical_id:
                return _error(404, "not_found", "route not found")
            return 200, repo.entity_detail(canonical_id)

        return _error(404, "not_found", "route not found")
    except ReadModelNotFound as exc:
        return _error(404, "not_found", str(exc))
    except ReadModelError as exc:
        return _error(400, "bad_request", str(exc))
