"""The single public history read entry, backed by immutable editions."""

from __future__ import annotations

import re
from urllib.parse import parse_qs

import history_edition_store
from common import PersistenceError
from read_common import ReadModelError, ReadModelNotFound


PREFIX = "/v0/history"
_VERSION_RE = re.compile(r"^[0-9a-f]{64}$")
_PARAGRAPH_RE = re.compile(r"^hp_[0-9a-f]{24}$")
_CONCLUSION_RE = re.compile(r"^hcon_[0-9a-f]{24}$")


def _query(raw: str, allowed: set[str]) -> dict[str, str]:
    query = parse_qs(raw, keep_blank_values=True)
    if set(query) - allowed or any(len(values) != 1 for values in query.values()):
        raise ReadModelError("unknown or repeated history query parameter")
    return {name: values[0] for name, values in query.items()}


def _int(query: dict[str, str], key: str, default: int, low: int, high: int | None = None) -> int:
    raw = query.get(key, str(default))
    if not re.fullmatch(r"0|[1-9][0-9]*", raw):
        raise ReadModelError(f"{key} must be an integer")
    value = int(raw)
    if value < low or (high is not None and value > high):
        if high is None:
            raise ReadModelError(f"{key} must be at least {low}")
        raise ReadModelError(f"{key} must be between {low} and {high}")
    return value


def _version(query: dict[str, str]) -> str | None:
    value = query.get("version")
    if value is not None and not _VERSION_RE.fullmatch(value):
        raise ReadModelError("invalid history edition version")
    return value


def _edition(conn, query: dict[str, str], *, required: bool = True) -> dict | None:
    version = _version(query)
    try:
        metadata = (
            history_edition_store.read_edition_metadata(conn, version)
            if version is not None
            else history_edition_store.read_latest_metadata(conn)
        )
    except (PersistenceError, ValueError) as exc:
        raise ReadModelError(str(exc)) from exc
    if metadata is None:
        if version is not None or required:
            raise ReadModelNotFound("this history edition version is not published")
        return None
    return metadata


def _directory_payload(metadata: dict | None) -> dict:
    # ``edition`` is the canonical T10 field.  ``publication`` remains a
    # response-shape alias for existing clients; it never selects a batch or
    # changes the fixed edition semantics.
    return {
        "schema": "chronicle.history-directory",
        "version": "0.1",
        "edition": metadata,
        "publication": metadata,
    }


def dispatch_history(conn, path: str, raw_query: str) -> dict:
    if path == PREFIX:
        query = _query(raw_query, {"version"})
        return _directory_payload(_edition(conn, query, required=False))

    if path == PREFIX + "/paragraphs":
        query = _query(raw_query, {"version", "start", "at", "limit"})
        if "at" in query and "start" in query:
            raise ReadModelError("choose either at or start")
        if not query.get("version"):
            raise ReadModelError("history reads require a fixed edition version")
        version = _version(query)
        assert version is not None
        _edition(conn, query)
        limit = _int(query, "limit", 20, 1, 50)
        if "at" in query and not _PARAGRAPH_RE.fullmatch(query["at"]):
            raise ReadModelError("invalid historical paragraph id")
        start = _int(query, "start", 0, 0) if "at" not in query else 0
        try:
            return history_edition_store.read_paragraph_page(
                conn, version=version, start=start, limit=limit, at=query.get("at")
            )
        except history_edition_store.HistoryEditionNotFound as exc:
            raise ReadModelNotFound(str(exc)) from exc
        except (PersistenceError, ValueError) as exc:
            raise ReadModelError(str(exc)) from exc

    if path.startswith(PREFIX + "/conclusions/"):
        query = _query(raw_query, {"version"})
        if not query.get("version"):
            raise ReadModelError("history reads require a fixed edition version")
        version = _version(query)
        assert version is not None
        conclusion_id = path[len(PREFIX + "/conclusions/"):]
        if not _CONCLUSION_RE.fullmatch(conclusion_id):
            raise ReadModelError("invalid historical conclusion id")
        _edition(conn, query)
        try:
            return history_edition_store.read_conclusion(
                conn, version=version, conclusion_id=conclusion_id
            )
        except history_edition_store.HistoryEditionNotFound as exc:
            raise ReadModelNotFound(str(exc)) from exc
        except (PersistenceError, ValueError) as exc:
            raise ReadModelError(str(exc)) from exc

    raise ReadModelNotFound("history route not found")
