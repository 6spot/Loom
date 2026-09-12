"""Chronicle C2-R3-T09 read-only source-reading person-state domain API.

This module is the bounded read surface over the C2-R3-T05 person-state store
(``person_state_store.py``) fixed by ``apps/chronicle/docs/person-state-reading.md``
section 7. It serves the two *source reading* product GET contracts:

    GET /v0/reading-streams/{stream_id}/units/{unit_id}/people
        ?catalog=&limit=6&cursor=
    GET /v0/reading-streams/{stream_id}/units/{unit_id}/people/{person_id}/states
        ?catalog=&section=identities|changes|evidence&phase_id=&item_id=&limit=20&cursor=
    GET /v0/reading-streams/{stream_id}/units/{unit_id}/places
        ?catalog=&phase_id=&limit=20&cursor=
    GET /v0/reading-streams/{stream_id}/units/{unit_id}/places/{place_id}/states
        ?catalog=&section=places|evidence&phase_id=&item_id=&limit=20&cursor=

There is deliberately no router/client wiring and no SQL here: the top-level
Python router, the Rust public boundary and the typed client belong to T10. The
summary, states and evidence pages are bounded keyset reads through the T05
store's ``list_unit_people`` / ``list_unit_person_states`` /
``list_state_item_evidence`` / ``list_unit_places`` /
``list_place_state_item_evidence`` entries; SQL and the database driver stay
in the T05 store. Every read is SELECT-only and never makes a semantic judgement,
calls a model or writes back.

Semantics:

- A response is one T01 DTO page (``unit_people_page`` / ``person_state_page`` /
  ``state_evidence_page``), not wrapped in another envelope. The page already
  carries ``stream_id``, ``unit_id``, ``catalog_sha``, ``publication_id`` and
  ``state_manifest_sha``, so the client can pin the exact immutable snapshot.
- An omitted ``catalog`` is resolved once with the same snapshot resolver the
  other reading routes use (newest ``publication_sequence``) and echoed in the
  response and cursors; a supplied catalog must be visible to the stream's own
  published manifest. An older snapshot never sees a later state manifest.
- The compiled summary members must be part of the reading unit's own
  ``context_entities`` with the matching ``kind`` (``person`` or ``place``);
  a manifest that lists a person/place outside its typed unit context is an
  internal inconsistency (explicit 409), while an addressed person/place
  outside context is a 404. Neither is silently dropped.
- The summary / detail / evidence pages are reduced to whole leading entries so
  the serialized response stays within ``summary_max_bytes`` /
  ``detail_max_bytes`` / ``evidence_max_bytes``; an entry is never truncated and
  the returned cursor still reaches the rest.
- A malformed parameter, a repeated/unknown parameter or a cursor bound to
  another scope is a 400; an unknown stream/unit/person/item/phase or an
  invisible snapshot is a 404; an internally missing/short compiled record is a
  409.
"""

from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

_PERSISTENCE_DIR = Path(__file__).resolve().parent.parent / "persistence"
if str(_PERSISTENCE_DIR) not in sys.path:
    sys.path.insert(0, str(_PERSISTENCE_DIR))

import person_state_contract as _contract  # noqa: E402
import person_state_store as _store  # noqa: E402
import reading_store as _reading_store  # noqa: E402
from common import PersistenceError, canonical_json_bytes  # noqa: E402

PREFIX = "/v0/reading-streams"

READING_VERSION = "0.1"
_SUMMARY_SCHEMA = "chronicle.reading-unit-people"
_STATES_SCHEMA = "chronicle.reading-person-states"
_EVIDENCE_SCHEMA = "chronicle.reading-person-evidence"

_LIMITS = _contract.PersonStateLimits()
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ITEM_ID_RE = re.compile(r"^psi_[0-9a-f]{24}$")
_PHASE_ID_RE = re.compile(r"^ph_[0-9]{3,}$")

SUMMARY_SECTIONS = ("identities", "changes")
DETAIL_SECTIONS = ("identities", "changes", "evidence")
PLACE_SECTIONS = ("places", "evidence")

#: Reserve room in a page budget for the opaque cursor and JSON envelope.
_CURSOR_MARGIN_BYTES = 1024

#: ``PersistenceError`` messages that mean a published record is internally
#: missing even though the addressed stream/unit exists (explicit 409).
_INCONSISTENT_MARKERS = (
    "unknown person-state manifest",
    "does not cover unit",
)

#: ``PersistenceError`` messages that name a missing reader-visible member.
_NOT_FOUND_MARKERS = (
    "unknown reading stream",
    "unknown reading unit",
    "unknown snapshot catalog",
    "unknown catalog",
    "not visible in snapshot",
    "unknown person",
    "unknown place",
    "unknown item",
    "is not bound to this unit",
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ReadingPeopleError(RuntimeError):
    """Base error for the source-reading person-state domain queries."""

    code = "internal"
    status = 500


class ReadingPeopleBadRequest(ReadingPeopleError):
    """Invalid parameters or a cursor bound to another read scope."""

    code = "bad_request"
    status = 400


class ReadingPeopleNotFound(ReadingPeopleError):
    """Unknown or snapshot-invisible stream/unit/person/item/phase."""

    code = "not_found"
    status = 404


class ReadingPeopleInconsistent(ReadingPeopleError):
    """Published person-state content is internally missing or inconsistent."""

    code = "inconsistent"
    status = 409


def error_payload(code: str, message: str) -> dict[str, Any]:
    return {
        "schema": "chronicle.error",
        "version": READING_VERSION,
        "error": {"code": code, "message": message},
    }


# ---------------------------------------------------------------------------
# Small validators
# ---------------------------------------------------------------------------


def _require_text(value: Any, description: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReadingPeopleBadRequest(f"{description} must be a non-empty string")
    return value


def _require_uuid(value: Any, description: str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ReadingPeopleBadRequest(f"{description} must be a UUID") from exc


def _require_sha(value: Any, description: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.match(value):
        raise ReadingPeopleBadRequest(
            f"{description} must be a lowercase hex SHA-256 string"
        )
    return value


def _require_phase_id(value: Any, description: str) -> str:
    text = _require_text(value, description)
    if not _PHASE_ID_RE.match(text):
        raise ReadingPeopleBadRequest(f"{description} must look like ph_<digits>")
    return text


def _require_item_id(value: Any, description: str) -> str:
    text = _require_text(value, description)
    if not _ITEM_ID_RE.match(text):
        raise ReadingPeopleBadRequest(f"{description} must look like psi_<24 hex>")
    return text


def _require_section(value: Any) -> str:
    if value not in DETAIL_SECTIONS:
        raise ReadingPeopleBadRequest(
            f"section must be one of {'|'.join(DETAIL_SECTIONS)}"
        )
    return value


def _require_place_section(value: Any) -> str:
    if value not in PLACE_SECTIONS:
        raise ReadingPeopleBadRequest(
            f"section must be one of {'|'.join(PLACE_SECTIONS)}"
        )
    return value


def _validate_limit(value: Any, *, maximum: int, what: str = "limit") -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > maximum:
        raise ReadingPeopleBadRequest(
            f"{what} must be an integer between 1 and {maximum}"
        )
    return value


def _byte_size(value: Any) -> int:
    return len(canonical_json_bytes(value))


# ---------------------------------------------------------------------------
# Query parsing (mirrors the shared reading router contract)
# ---------------------------------------------------------------------------


def _scalar_query(raw_query: str, allowed: set[str]) -> dict[str, str]:
    query = parse_qs(raw_query or "", keep_blank_values=True)
    unknown = sorted(set(query) - allowed)
    if unknown:
        raise ReadingPeopleBadRequest(
            f"unknown query parameter(s): {', '.join(unknown)}"
        )
    scalars: dict[str, str] = {}
    for name, values in query.items():
        if len(values) != 1:
            raise ReadingPeopleBadRequest(f"query parameter {name} must appear once")
        scalars[name] = values[0]
    return scalars


def _int_param(query: dict[str, str], name: str, default: int) -> int:
    if name not in query:
        return default
    try:
        return int(query[name])
    except (TypeError, ValueError) as exc:
        raise ReadingPeopleBadRequest(
            f"query parameter {name} must be an integer"
        ) from exc


# ---------------------------------------------------------------------------
# Snapshot / membership resolution
# ---------------------------------------------------------------------------


def _resolve_catalog(conn, catalog_sha: str | None) -> str:
    """Resolve (and validate) the snapshot catalog for this read.

    A supplied catalog is only format-checked here; existence and stream
    visibility are enforced against the published manifest below. An omitted
    catalog resolves the newest published snapshot exactly once, like the rest
    of the reading API, so cursors and responses stay pinned to one snapshot.
    """
    if catalog_sha is not None:
        return _require_sha(catalog_sha, "catalog")
    from reader_streams import (  # local import avoids a module cycle
        ReadingStreamBadRequest,
        ReadingStreamNotFound,
        resolve_snapshot,
    )

    try:
        return resolve_snapshot(conn)["catalog_sha"]
    except ReadingStreamNotFound as exc:
        raise ReadingPeopleNotFound(str(exc)) from exc
    except ReadingStreamBadRequest as exc:
        raise ReadingPeopleBadRequest(str(exc)) from exc


def _read_unit(conn, stream_id: uuid.UUID, unit_id: str, catalog_sha: str) -> dict[str, Any]:
    try:
        return _reading_store.read_reading_unit(
            conn,
            stream_id=stream_id,
            unit_id=unit_id,
            snapshot_catalog_sha=catalog_sha,
        )
    except PersistenceError as exc:
        raise _classify_store_error(exc)


def _context_person_ids(unit: dict[str, Any]) -> set[str]:
    person_ids: set[str] = set()
    for entity in unit.get("context_entities") or []:
        if not isinstance(entity, dict) or entity.get("kind") != "person":
            continue
        canonical_id = entity.get("canonical_id")
        if isinstance(canonical_id, str) and canonical_id:
            person_ids.add(canonical_id)
    return person_ids


def _context_place_ids(unit: dict[str, Any]) -> set[str]:
    """Return both aliases for context entities explicitly typed as places."""
    place_ids: set[str] = set()
    for entity in unit.get("context_entities") or []:
        if not isinstance(entity, dict) or entity.get("kind") != "place":
            continue
        for key in (entity.get("canonical_id"), entity.get("entity_ref")):
            if isinstance(key, str) and key:
                place_ids.add(key)
    return place_ids


# ---------------------------------------------------------------------------
# Store call / error classification
# ---------------------------------------------------------------------------


def _classify_store_error(exc: PersistenceError) -> ReadingPeopleError:
    text = str(exc)
    if any(marker in text for marker in _INCONSISTENT_MARKERS):
        return ReadingPeopleInconsistent(text)
    if any(marker in text for marker in _NOT_FOUND_MARKERS):
        return ReadingPeopleNotFound(text)
    return ReadingPeopleInconsistent(text)


def _call_store(func, conn, **kwargs) -> dict[str, Any]:
    try:
        return func(conn, **kwargs)
    except _store.PersonStateCursorError as exc:
        raise ReadingPeopleBadRequest(str(exc)) from exc
    except PersistenceError as exc:
        raise _classify_store_error(exc) from exc


def _validate_page(name: str, page: dict[str, Any]) -> dict[str, Any]:
    errors = _contract.validate_person_state_dto(name, page)
    if errors:
        raise ReadingPeopleInconsistent(
            f"published {name} is not a valid DTO: {'; '.join(errors)}"
        )
    return page


def _require_compiled_items(items: Any, description: str) -> None:
    """Fail closed when one published item exceeds ``compiled_item_max_bytes``.

    The page budget bounds the whole response, but ``person-state-reading.md`` §7
    also fixes ``compiled_item_max_bytes`` (64 KiB) for a single complete
    identity/change item. The publish boundary already rejects oversized items;
    this is the read-side second fence so a stored oversized item can never be
    served as a valid page.
    """
    for item in items or []:
        if _byte_size(item) > _LIMITS.compiled_item_max_bytes:
            raise ReadingPeopleInconsistent(
                f"a published {description} item exceeds compiled_item_max_bytes"
            )


# ---------------------------------------------------------------------------
# Response budgets (whole entries only)
# ---------------------------------------------------------------------------


def _fit_summary_page(conn, page, *, stream_id, unit_id, catalog_sha, cursor):
    people = list(page["people"])
    while people and _byte_size(
        {**page, "people": people, "people_count": len(people)}
    ) + _CURSOR_MARGIN_BYTES > _LIMITS.summary_max_bytes:
        people = people[:-1]
    if not people and page["people"]:
        raise ReadingPeopleInconsistent(
            "a single compiled person summary exceeds summary_max_bytes"
        )
    if len(people) == len(page["people"]):
        return page
    return _call_store(
        _store.list_unit_people,
        conn,
        stream_id=stream_id,
        unit_id=unit_id,
        catalog_sha=catalog_sha,
        limit=len(people),
        cursor=cursor,
    )


def _fit_place_page(conn, page, *, stream_id, unit_id, place_id, phase_id, catalog_sha, cursor):
    places = list(page["places"])
    while places and _byte_size(
        {**page, "places": places}
    ) + _CURSOR_MARGIN_BYTES > _LIMITS.detail_max_bytes:
        places = places[:-1]
    if not places and page["places"]:
        raise ReadingPeopleInconsistent(
            "a single compiled place state item exceeds detail_max_bytes"
        )
    if len(places) == len(page["places"]):
        return page
    return _call_store(
        _store.list_unit_places,
        conn,
        stream_id=stream_id,
        unit_id=unit_id,
        place_id=place_id,
        phase_id=phase_id,
        catalog_sha=catalog_sha,
        limit=len(places),
        cursor=cursor,
    )


def _fit_detail_page(conn, page, *, section, **scope):
    key = "items" if section == "identities" else "changes"
    rows = list(page[key])
    while rows and _byte_size(
        {**page, key: rows, "item_count": len(rows)}
    ) + _CURSOR_MARGIN_BYTES > _LIMITS.detail_max_bytes:
        rows = rows[:-1]
    if not rows and page[key]:
        raise ReadingPeopleInconsistent(
            "a single compiled state item exceeds detail_max_bytes"
        )
    if len(rows) == len(page[key]):
        return page
    return _call_store(
        _store.list_unit_person_states,
        conn,
        section=section,
        limit=len(rows),
        **scope,
    )


def _fit_evidence_page(conn, page, *, store_func=None, **scope):
    store_func = store_func or _store.list_state_item_evidence
    descriptors = list(page["descriptors"])
    while descriptors and _byte_size(
        {**page, "descriptors": descriptors, "descriptor_count": len(descriptors)}
    ) + _CURSOR_MARGIN_BYTES > _LIMITS.evidence_max_bytes:
        descriptors = descriptors[:-1]
    if not descriptors and page["descriptors"]:
        raise ReadingPeopleInconsistent(
            "a single evidence page entry exceeds evidence_max_bytes"
        )
    if len(descriptors) == len(page["descriptors"]):
        return page
    return _call_store(
        store_func,
        conn,
        limit=len(descriptors),
        **scope,
    )


# ---------------------------------------------------------------------------
# Domain queries
# ---------------------------------------------------------------------------


def unit_people(
    conn,
    *,
    stream_id: Any,
    unit_id: Any,
    catalog_sha: str | None = None,
    limit: int = 6,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return one bounded page of the current unit's compiled person summaries."""
    stream_uuid = _require_uuid(stream_id, "stream_id")
    unit_id = _require_text(unit_id, "unit_id")
    limit = _validate_limit(limit, maximum=_LIMITS.page_max_limit)
    catalog = _resolve_catalog(conn, catalog_sha)
    unit = _read_unit(conn, stream_uuid, unit_id, catalog)
    context = _context_person_ids(unit)
    page = _call_store(
        _store.list_unit_people,
        conn,
        stream_id=stream_uuid,
        unit_id=unit_id,
        catalog_sha=catalog,
        limit=limit,
        cursor=cursor,
    )
    for person in page["people"]:
        if person["person_id"] not in context:
            raise ReadingPeopleInconsistent(
                f"compiled person {person['person_id']!r} is not part of unit "
                f"{unit_id!r} context"
            )
        _require_compiled_items(person["identities"], "identity")
        _require_compiled_items(person["changes"], "change")
    page = _fit_summary_page(
        conn,
        page,
        stream_id=stream_uuid,
        unit_id=unit_id,
        catalog_sha=catalog,
        cursor=cursor,
    )
    return _validate_page("unit_people_page", page)


def unit_places(
    conn,
    *,
    stream_id: Any,
    unit_id: Any,
    place_id: Any | None = None,
    catalog_sha: str | None = None,
    phase_id: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return one bounded page of administration/control place state items."""
    stream_uuid = _require_uuid(stream_id, "stream_id")
    unit_id = _require_text(unit_id, "unit_id")
    if place_id is not None:
        place_id = _require_text(place_id, "place_id")
    if phase_id is not None:
        phase_id = _require_phase_id(phase_id, "phase_id")
    limit = _validate_limit(limit, maximum=_LIMITS.page_max_limit)
    catalog = _resolve_catalog(conn, catalog_sha)
    unit = _read_unit(conn, stream_uuid, unit_id, catalog)
    context_places = _context_place_ids(unit)
    if place_id is not None and place_id not in context_places:
        raise ReadingPeopleNotFound(
            f"place {place_id!r} is not part of unit {unit_id!r} context"
        )
    page = _call_store(
        _store.list_unit_places,
        conn,
        stream_id=stream_uuid,
        unit_id=unit_id,
        place_id=place_id,
        phase_id=phase_id,
        catalog_sha=catalog,
        limit=limit,
        cursor=cursor,
    )
    for place in page["places"]:
        if place["place_id"] not in context_places:
            raise ReadingPeopleInconsistent(
                f"compiled place {place['place_id']!r} is not part of unit "
                f"{unit_id!r} context"
            )
    _require_compiled_items(page["places"], "place state")
    page = _fit_place_page(
        conn,
        page,
        stream_id=stream_uuid,
        unit_id=unit_id,
        place_id=place_id,
        phase_id=phase_id,
        catalog_sha=catalog,
        cursor=cursor,
    )
    return _validate_page("place_state_page", page)


def unit_place_states(
    conn,
    *,
    stream_id: Any,
    unit_id: Any,
    place_id: Any,
    section: Any,
    catalog_sha: str | None = None,
    phase_id: str | None = None,
    item_id: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return a place-state page or evidence page for one place."""
    stream_uuid = _require_uuid(stream_id, "stream_id")
    unit_id = _require_text(unit_id, "unit_id")
    place_id = _require_text(place_id, "place_id")
    section = _require_place_section(section)
    if phase_id is not None:
        phase_id = _require_phase_id(phase_id, "phase_id")
    if section == "evidence":
        if item_id is None:
            raise ReadingPeopleBadRequest("section=evidence requires item_id")
        item_id = _require_item_id(item_id, "item_id")
    elif item_id is not None:
        raise ReadingPeopleBadRequest(
            "item_id is only valid together with section=evidence"
        )
    limit = _validate_limit(limit, maximum=_LIMITS.page_max_limit)
    catalog = _resolve_catalog(conn, catalog_sha)
    unit = _read_unit(conn, stream_uuid, unit_id, catalog)
    if place_id not in _context_place_ids(unit):
        raise ReadingPeopleNotFound(
            f"place {place_id!r} is not part of unit {unit_id!r} context"
        )
    if section == "places":
        return unit_places(
            conn,
            stream_id=stream_uuid,
            unit_id=unit_id,
            place_id=place_id,
            catalog_sha=catalog,
            phase_id=phase_id,
            limit=limit,
            cursor=cursor,
        )
    page = _call_store(
        _store.list_place_state_item_evidence,
        conn,
        stream_id=stream_uuid,
        unit_id=unit_id,
        place_id=place_id,
        item_id=item_id,
        phase_id=phase_id,
        catalog_sha=catalog,
        limit=limit,
        cursor=cursor,
    )
    page = _fit_evidence_page(
        conn,
        page,
        store_func=_store.list_place_state_item_evidence,
        stream_id=stream_uuid,
        unit_id=unit_id,
        place_id=place_id,
        item_id=item_id,
        phase_id=phase_id,
        catalog_sha=catalog,
        cursor=cursor,
    )
    return _validate_page("state_evidence_page", page)


def unit_person_states(
    conn,
    *,
    stream_id: Any,
    unit_id: Any,
    person_id: Any,
    section: Any,
    catalog_sha: str | None = None,
    phase_id: str | None = None,
    item_id: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return one bounded page of a person's identities, changes or evidence."""
    stream_uuid = _require_uuid(stream_id, "stream_id")
    unit_id = _require_text(unit_id, "unit_id")
    person_id = _require_text(person_id, "person_id")
    section = _require_section(section)
    if phase_id is not None:
        phase_id = _require_phase_id(phase_id, "phase_id")
    if section == "evidence":
        if item_id is None:
            raise ReadingPeopleBadRequest("section=evidence requires item_id")
        item_id = _require_item_id(item_id, "item_id")
    elif item_id is not None:
        raise ReadingPeopleBadRequest(
            "item_id is only valid together with section=evidence"
        )
    limit = _validate_limit(limit, maximum=_LIMITS.page_max_limit)
    catalog = _resolve_catalog(conn, catalog_sha)
    unit = _read_unit(conn, stream_uuid, unit_id, catalog)
    if person_id not in _context_person_ids(unit):
        raise ReadingPeopleNotFound(
            f"person {person_id!r} is not part of unit {unit_id!r} context"
        )
    if section == "evidence":
        page = _call_store(
            _store.list_state_item_evidence,
            conn,
            stream_id=stream_uuid,
            unit_id=unit_id,
            person_id=person_id,
            item_id=item_id,
            phase_id=phase_id,
            catalog_sha=catalog,
            limit=limit,
            cursor=cursor,
        )
        page = _fit_evidence_page(
            conn,
            page,
            stream_id=stream_uuid,
            unit_id=unit_id,
            person_id=person_id,
            item_id=item_id,
            phase_id=phase_id,
            catalog_sha=catalog,
            cursor=cursor,
        )
        return _validate_page("state_evidence_page", page)
    page = _call_store(
        _store.list_unit_person_states,
        conn,
        stream_id=stream_uuid,
        unit_id=unit_id,
        person_id=person_id,
        section=section,
        phase_id=phase_id,
        catalog_sha=catalog,
        limit=limit,
        cursor=cursor,
    )
    _require_compiled_items(page["items"], "identity")
    _require_compiled_items(page["changes"], "change")
    page = _fit_detail_page(
        conn,
        page,
        section=section,
        stream_id=stream_uuid,
        unit_id=unit_id,
        person_id=person_id,
        phase_id=phase_id,
        catalog_sha=catalog,
        cursor=cursor,
    )
    return _validate_page("person_state_page", page)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _match_route(path: str) -> dict[str, str] | None:
    prefix = PREFIX + "/"
    if not path.startswith(prefix):
        return None
    parts = path[len(prefix):].split("/")
    if len(parts) == 4 and parts[1] == "units" and parts[3] == "people" and parts[0] and parts[2]:
        return {"kind": "people", "stream_id": parts[0], "unit_id": parts[2]}
    if len(parts) == 4 and parts[1] == "units" and parts[3] == "places" and parts[0] and parts[2]:
        return {"kind": "places", "stream_id": parts[0], "unit_id": parts[2]}
    if (
        len(parts) == 6
        and parts[1] == "units"
        and parts[3] == "people"
        and parts[5] == "states"
        and parts[0]
        and parts[2]
        and parts[4]
    ):
        return {
            "kind": "states",
            "stream_id": parts[0],
            "unit_id": parts[2],
            "person_id": parts[4],
        }
    if (
        len(parts) == 6
        and parts[1] == "units"
        and parts[3] == "places"
        and parts[5] == "states"
        and parts[0]
        and parts[2]
        and parts[4]
    ):
        return {
            "kind": "place_states",
            "stream_id": parts[0],
            "unit_id": parts[2],
            "place_id": parts[4],
        }
    return None


def dispatch_reading_people(
    conn, method: str, path: str, raw_query: str = ""
) -> tuple[int, dict[str, Any]] | None:
    """Dispatch the source-reading people/place-state product GET routes.

    Returns ``None`` (not an error) when ``path`` is not one of this module's
    routes so the shared router can try the next domain dispatcher. A matched
    route with a non-GET method is a 405.
    """
    route = _match_route(path)
    if route is None:
        return None
    if method != "GET":
        return 405, error_payload("method_not_allowed", "only GET is supported")
    try:
        if route["kind"] == "people":
            query = _scalar_query(raw_query, {"catalog", "limit", "cursor"})
            page = unit_people(
                conn,
                stream_id=route["stream_id"],
                unit_id=route["unit_id"],
                catalog_sha=query.get("catalog"),
                limit=_int_param(query, "limit", 6),
                cursor=query.get("cursor"),
            )
            return 200, page
        if route["kind"] == "places":
            query = _scalar_query(raw_query, {"catalog", "phase_id", "limit", "cursor"})
            page = unit_places(
                conn,
                stream_id=route["stream_id"],
                unit_id=route["unit_id"],
                catalog_sha=query.get("catalog"),
                phase_id=query.get("phase_id"),
                limit=_int_param(query, "limit", 20),
                cursor=query.get("cursor"),
            )
            return 200, page
        if route["kind"] == "place_states":
            query = _scalar_query(
                raw_query, {"catalog", "section", "phase_id", "item_id", "limit", "cursor"}
            )
            if "section" not in query:
                raise ReadingPeopleBadRequest("query parameter section is required")
            page = unit_place_states(
                conn,
                stream_id=route["stream_id"],
                unit_id=route["unit_id"],
                place_id=route["place_id"],
                section=query["section"],
                catalog_sha=query.get("catalog"),
                phase_id=query.get("phase_id"),
                item_id=query.get("item_id"),
                limit=_int_param(query, "limit", 20),
                cursor=query.get("cursor"),
            )
            return 200, page
        query = _scalar_query(
            raw_query, {"catalog", "section", "phase_id", "item_id", "limit", "cursor"}
        )
        if "section" not in query:
            raise ReadingPeopleBadRequest("query parameter section is required")
        page = unit_person_states(
            conn,
            stream_id=route["stream_id"],
            unit_id=route["unit_id"],
            person_id=route["person_id"],
            section=query["section"],
            catalog_sha=query.get("catalog"),
            phase_id=query.get("phase_id"),
            item_id=query.get("item_id"),
            limit=_int_param(query, "limit", 20),
            cursor=query.get("cursor"),
        )
        return 200, page
    except ReadingPeopleNotFound as exc:
        return 404, error_payload("not_found", str(exc))
    except ReadingPeopleBadRequest as exc:
        return 400, error_payload("bad_request", str(exc))
    except ReadingPeopleInconsistent as exc:
        return 409, error_payload("inconsistent", str(exc))


__all__ = [
    "DETAIL_SECTIONS",
    "PLACE_SECTIONS",
    "PREFIX",
    "READING_VERSION",
    "ReadingPeopleBadRequest",
    "ReadingPeopleError",
    "ReadingPeopleInconsistent",
    "ReadingPeopleNotFound",
    "SUMMARY_SECTIONS",
    "dispatch_reading_people",
    "error_payload",
    "unit_people",
    "unit_places",
    "unit_place_states",
    "unit_person_states",
]
