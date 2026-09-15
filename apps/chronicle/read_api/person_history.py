"""HTTP routing for the published person-history read surface (C3-T13).

The route is intentionally parallel to the global history reader while being
scoped by a canonical person and an immutable person-history version:

``/v0/entities/{person_id}/history``
    published metadata (and an optional exact main-history locator);
``/v0/entities/{person_id}/history/paragraphs``
    bounded prose pages;
``/v0/entities/{person_id}/history/conclusions/{id}``
    one conclusion with source evidence expanded on demand.

Only the Rust boundary exposes the corresponding ``/api/v1/public`` paths;
this module owns the Python-side query and error contract.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs

from read_common import ReadModelError
from person_history_repository import PersonHistoryReadRepository


PREFIX = "/v0/entities/"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _error(status: int, code: str, message: str) -> tuple[int, dict[str, Any]]:
    return status, {
        "schema": "chronicle.error",
        "version": "0.1",
        "error": {"code": code, "message": message},
    }


def _query(raw_query: str, allowed: set[str]) -> dict[str, str]:
    parsed = parse_qs(raw_query or "", keep_blank_values=True)
    unknown = sorted(set(parsed) - allowed)
    if unknown:
        raise ReadModelError(
            f"unknown query parameter(s): {', '.join(unknown)}"
        )
    result: dict[str, str] = {}
    for name, values in parsed.items():
        if len(values) != 1:
            raise ReadModelError(f"query parameter {name} must appear once")
        result[name] = values[0]
    return result


def _one_alias(query: dict[str, str], names: tuple[str, ...]) -> str | None:
    present = [(name, query[name]) for name in names if name in query]
    if len(present) > 1:
        raise ReadModelError(
            f"use only one of {', '.join(name for name, _value in present)}"
        )
    return present[0][1] if present else None


def _integer(query: dict[str, str], name: str, default: int, *, maximum: int | None = None) -> int:
    value = query.get(name, str(default))
    if not re.fullmatch(r"0|[1-9][0-9]*", value):
        raise ReadModelError(f"{name} must be a nonnegative integer")
    parsed = int(value)
    if maximum is not None and parsed > maximum:
        raise ReadModelError(f"{name} must be between 1 and {maximum}")
    return parsed


def _fixed_person_version(query: dict[str, str]) -> str:
    explicit = _one_alias(
        query,
        ("person_version", "person_history_version", "history_version"),
    )
    shorthand = query.get("version")
    if explicit is not None and shorthand is not None:
        raise ReadModelError(
            "person-history reads require one fixed person-history version"
        )
    version = explicit if explicit is not None else shorthand
    if version is None or not _SHA_RE.fullmatch(version):
        raise ReadModelError(
            "person-history reads require a lowercase SHA-256 version"
        )
    return version


def _metadata_query(query: dict[str, str]) -> tuple[str | None, dict[str, str] | None]:
    """Separate the fixed person version from the optional main locator.

    ``version`` keeps the same shorthand as the existing history API.  With
    ``paragraph_id`` it is the source main-history version, while an explicit
    ``person_version``/``history_version`` pins the biography.  The explicit
    ``main_history_version`` spelling removes that overload for callers that
    need to send both versions.
    """

    person_version_alias = _one_alias(
        query,
        ("person_version", "person_history_version", "history_version"),
    )
    shorthand = query.get("version")
    main_version = query.get("main_history_version")
    paragraph_id = query.get("paragraph_id")
    phase_id = query.get("phase_id")
    locator_requested = any(
        value is not None for value in (main_version, paragraph_id, phase_id)
    )
    if not locator_requested:
        if person_version_alias is not None and shorthand is not None:
            raise ReadModelError(
                "person-history metadata requires one fixed person-history version"
            )
        return person_version_alias or shorthand, None
    if paragraph_id is None:
        raise ReadModelError("main-history locator requires paragraph_id")
    if main_version is None:
        if shorthand is None:
            raise ReadModelError(
                "main-history locator requires version or main_history_version"
            )
        main_version = shorthand
        person_version = person_version_alias
    else:
        # When the explicit main spelling is used, an unqualified version is
        # the optional fixed person-history version.  Supplying both forms of
        # person version remains ambiguous and is rejected above.
        if person_version_alias is not None and shorthand is not None:
            raise ReadModelError(
                "person-history metadata requires one fixed person-history version"
            )
        person_version = person_version_alias or shorthand
    if not _SHA_RE.fullmatch(main_version):
        raise ReadModelError(
            "main-history version must be a lowercase SHA-256 string"
        )
    locator = {
        "version": main_version,
        "paragraph_id": paragraph_id,
    }
    if phase_id is not None:
        locator["phase_id"] = phase_id
    return person_version, locator


def _metadata(repo: PersonHistoryReadRepository, person_id: str, raw_query: str):
    query = _query(
        raw_query,
        {
            "version",
            "person_version",
            "person_history_version",
            "history_version",
            "main_history_version",
            "paragraph_id",
            "phase_id",
        },
    )
    person_version, locator = _metadata_query(query)
    if person_version is not None and not _SHA_RE.fullmatch(person_version):
        raise ReadModelError(
            "person-history version must be a lowercase SHA-256 string"
        )
    return 200, repo.read_metadata(
        person_id=person_id,
        version=person_version,
        main_locator=locator,
    )


def _paragraphs(repo: PersonHistoryReadRepository, person_id: str, raw_query: str):
    query = _query(
        raw_query,
        {
            "version",
            "person_version",
            "person_history_version",
            "history_version",
            "start",
            "at",
            "limit",
        },
    )
    if "at" in query and "start" in query:
        raise ReadModelError("choose either at or start")
    version = _fixed_person_version(query)
    limit = _integer(query, "limit", 20, maximum=50)
    if limit < 1:
        raise ReadModelError("limit must be between 1 and 50")
    start = _integer(query, "start", 0)
    return 200, repo.read_paragraph_page(
        person_id=person_id,
        version=version,
        start=start,
        limit=limit,
        at=query.get("at"),
    )


def _conclusion(
    repo: PersonHistoryReadRepository,
    person_id: str,
    conclusion_id: str,
    raw_query: str,
):
    query = _query(
        raw_query,
        {"version", "person_version", "person_history_version", "history_version"},
    )
    version = _fixed_person_version(query)
    return 200, repo.read_conclusion(
        person_id=person_id,
        version=version,
        conclusion_id=conclusion_id,
    )


def dispatch_person_history(
    repo,
    method: str,
    path: str,
    raw_query: str = "",
) -> tuple[int, dict[str, Any]] | None:
    """Dispatch one person-history path or return ``None`` for other paths."""

    if not path.startswith(PREFIX):
        return None
    if method != "GET":
        # ``router.dispatch`` rejects non-GET before reaching domain
        # dispatchers; keeping this branch makes direct contract tests and
        # future callers fail with the same typed response.
        return _error(405, "method_not_allowed", "only GET is supported")
    parts = path[len(PREFIX) :].split("/")
    if len(parts) < 2 or not parts[0] or parts[1] != "history":
        return None
    person_id = parts[0]
    reader = PersonHistoryReadRepository(repo.conn if hasattr(repo, "conn") else repo)
    if len(parts) == 2:
        return _metadata(reader, person_id, raw_query)
    if len(parts) == 3 and parts[2] == "paragraphs":
        return _paragraphs(reader, person_id, raw_query)
    if (
        len(parts) == 4
        and parts[2] == "conclusions"
        and parts[3]
    ):
        return _conclusion(reader, person_id, parts[3], raw_query)
    return _error(404, "not_found", "person-history route not found")


__all__ = ["PREFIX", "dispatch_person_history"]
