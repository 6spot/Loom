"""Chronicle C2-R3-T05 person-state store (application-owned persistence).

Narrow, immutable persistence for the third-round person-state artifacts fixed
by ``apps/chronicle/docs/person-state-reading.md`` section 6, behind
``CHRONICLE_DATABASE_URL`` (Architecture Amendment 0006). It never reads the
Loom database and never copies body text, full translations, Entity/Claim
tables or the job state machine; every row points at the existing publication /
stream / unit / catalog / assessment identity.

Write entries (all take the caller's already-open connection; none opens or
commits a transaction, so T08's unique publication transaction can commit the
catalog, every chapter publication, the reading index and the whole person-state
layer atomically):

- :func:`persist_person_state_assessments` — immutable reviewed assessment
  artifacts keyed by ``plan_fingerprint``. Same plan + same payload is a no-op;
  the same plan with different bytes raises :class:`PersistenceConflict`.
- :func:`persist_person_state_manifest` — the compiled per-stream state manifest
  plus the bounded per-unit person / item / evidence index. Idempotent on the
  complete normalized compiled input for one stream; different bytes raise
  :class:`PersistenceConflict`.
- :func:`persist_person_state_disagreements` — the immutable, catalog-scoped
  cross-source disagreement index. Idempotent per ``(catalog_sha,
  disagreement_id)``.

Read entries are SELECT-only and bounded. They never read the whole history and
slice it in Python: ordinal keysets use indexed ranges with ``limit + 1``.

- :func:`list_unit_people` — one bounded page of per-unit person summaries.
- :func:`list_unit_places` — one bounded page of per-unit administration /
  control place items.
- :func:`list_unit_person_states` — one bounded page of a person's identities
  or changes for the unit, optionally filtered by phase. When a snapshot
  ``catalog_sha`` is supplied it must be visible (the stream's origin catalog
  ``publication_sequence`` is ``<=`` the snapshot's), and that catalog's
  recorded disagreements are overlaid as extra ``source_disagreement`` reasons.
  The overlay can only add uncertainty; it never promotes a claim to clear.
- :func:`list_state_item_evidence` — one bounded page of evidence descriptors
  for one compiled item.
- :func:`list_place_state_item_evidence` — one bounded page of evidence
  descriptors for one compiled administration / control item.
- :func:`list_catalog_disagreements` — one bounded page of one catalog's
  immutable disagreement index (the only disagreement read path).

Inputs are plain JSON objects validated against the T01 machine contract
(:mod:`person_state_contract`). The store only ever allocates program-owned
values (hashes, ordinals, rankings); it refuses partially written input before
touching a row and the 0009 triggers are the second fence.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Iterable

from psycopg.types.json import Jsonb

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import person_state_contract as _contract  # noqa: E402
from common import (  # noqa: E402
    PersistenceConflict,
    PersistenceError,
    canonical_json_bytes,
    parse_uuid7,
    sha256_json,
)

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_PHASE_ID_RE = re.compile(r"^ph_[0-9]{3,}$")
_ITEM_ID_RE = re.compile(r"^psi_[0-9a-f]{24}$")

#: Bumped whenever the opaque cursor payload shape changes.
CURSOR_VERSION = 1

# Shared with the read API's whole-entry response fitting. Publication checks
# reserve the same room so an accepted descriptor can actually be read back.
STATE_PAGE_CURSOR_MARGIN_BYTES = 1024


class PersonStateCursorError(PersistenceError):
    """A pagination cursor is malformed or bound to a different read scope.

    The read API maps this to a 400-style bad request; a cursor minted for one
    stream/unit/person/section/phase/catalog/item can never be replayed against
    another scope, and malformed cursor values never reach PostgreSQL.
    """


PHASE_MODES = tuple(_contract.PHASE_MODES)
STATE_DIMENSIONS = tuple(_contract.STATE_DIMENSIONS)
PLACE_DIMENSIONS = tuple(_contract.PLACE_DIMENSIONS)
OPERATIONS = tuple(_contract.OPERATIONS)
QUALIFICATIONS = tuple(_contract.QUALIFICATIONS)
CERTAINTIES = tuple(_contract.CERTAINTIES)
REASON_CODES = tuple(_contract.REASON_CODES)
ATTRIBUTIONS = tuple(_contract.ATTRIBUTIONS)
EVIDENCE_RELATIONS = ("support", "supplement", "contradict", "background")
IMPORTANCES = ("primary", "other")
ITEM_KINDS = ("identity", "change")
SECTIONS = ("identities", "changes")

#: Mirrors ``person_state_contract._reason_text``; the unit test asserts the two
#: stay identical so the stored display text never drifts from the shared type.
_REASON_LABELS = {
    "tenure_unproven": "仅此前记载／任期未明",
    "order_unknown": "阶段先后不确定",
    "source_disagreement": "来源存在分歧",
    "attribution_uncertain": "引述／注文归属或限定未定",
    "evidence_uncertain": "有材料但结论仍不确定",
    "phase_not_reached": "属于当前阶段之后",
    "phase_not_begun": "尚未开始",
}


# ---------------------------------------------------------------------------
# Small validators / id helpers
# ---------------------------------------------------------------------------


def _require_uuid(value: Any, description: str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PersistenceError(f"{description} must be a UUID, got {value!r}") from exc


def _require_uuid7(value: Any, description: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return parse_uuid7(str(value), description)
    return parse_uuid7(value, description)


def _require_sha(value: Any, description: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.match(value):
        raise PersistenceError(f"{description} must be a lowercase hex SHA-256 string")
    return value


def _require_text(value: Any, description: str) -> str:
    if not isinstance(value, str) or not value:
        raise PersistenceError(f"{description} must be a non-empty string")
    return value


def _require_object(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PersistenceError(f"{description} must be a JSON object")
    return value


def _require_list(value: Any, description: str) -> list[Any]:
    if not isinstance(value, list):
        raise PersistenceError(f"{description} must be an array")
    return value


def _require_phase_id(value: Any, description: str) -> str:
    text = _require_text(value, description)
    if not _PHASE_ID_RE.match(text):
        raise PersistenceError(f"{description} must look like ph_<digits>, got {text!r}")
    return text


def _reason_text(codes: Iterable[str]) -> str:
    ordered = sorted(set(codes))
    return "；".join(_REASON_LABELS.get(code, code) for code in ordered)


def _normalize_reason_codes(value: Any, owner: str) -> list[str]:
    if value is None:
        return []
    items = _require_list(value, f"{owner}.reason_codes")
    result: list[str] = []
    for code in items:
        if not isinstance(code, str) or code not in REASON_CODES:
            raise PersistenceError(f"{owner}.reason_codes carries invalid code {code!r}")
        if code not in result:
            result.append(code)
    return sorted(result)


def _validate_dto(name: str, value: Any, owner: str) -> None:
    errors = _contract.validate_person_state_dto(name, value)
    if errors:
        raise PersistenceError(f"{owner} is not a valid {name}: {'; '.join(errors)}")


# ---------------------------------------------------------------------------
# Compiled-manifest validation (fail closed before any row is written)
# ---------------------------------------------------------------------------


def _require_compiled_item_size(item: dict[str, Any], owner: str) -> None:
    """Reject an oversized compiled item before any row is written.

    ``person-state-reading.md`` §7 fixes ``compiled_item_max_bytes`` (64 KiB) for
    one complete identity/change item. The schema validator does not bound text
    length, so the publish boundary enforces the byte cap explicitly.
    """
    limit = _contract.PersonStateLimits().compiled_item_max_bytes
    size = len(canonical_json_bytes(item))
    if size > limit:
        raise PersistenceError(
            f"{owner} is {size} bytes and exceeds compiled_item_max_bytes {limit}"
        )


def _normalize_identity_item(item: Any, owner: str) -> dict[str, Any]:
    item = dict(_require_object(item, owner))
    item.setdefault("value", None)
    item.setdefault("relation", None)
    item.setdefault("target", None)
    item.setdefault("target_id", None)
    item.setdefault("qualification", "ordinary")
    item.setdefault("current", False)
    item.setdefault("phase_ids", [])
    item.setdefault("reason_codes", [])
    item.setdefault("reason_text", _reason_text(item["reason_codes"]))
    item.setdefault("evidence_cursor", None)
    item.setdefault("source_facts", [])
    if not isinstance(item.get("source_facts"), list):
        raise PersistenceError(f"{owner}.source_facts must be an array")
    item["reason_codes"] = _normalize_reason_codes(item["reason_codes"], owner)
    # ``evidence_count`` is recomputed from the persisted descriptors later; a
    # placeholder keeps the DTO validation deterministic.
    if not isinstance(item.get("evidence_count"), int) or isinstance(item.get("evidence_count"), bool):
        item["evidence_count"] = len(item["source_facts"])
    _validate_dto("state_item", item, owner)
    _require_compiled_item_size(item, owner)
    return item


def _normalize_change_item(item: Any, owner: str) -> dict[str, Any]:
    item = dict(_require_object(item, owner))
    item.setdefault("value", None)
    item.setdefault("relation", None)
    item.setdefault("target", None)
    item.setdefault("from_phase_id", None)
    item.setdefault("reason_codes", [])
    item["reason_codes"] = _normalize_reason_codes(item["reason_codes"], owner)
    item.setdefault("source_facts", [])
    if not isinstance(item.get("source_facts"), list):
        raise PersistenceError(f"{owner}.source_facts must be an array")
    _validate_dto("state_change", item, owner)
    _require_compiled_item_size(item, owner)
    return item


def _normalize_place_item(item: Any, owner: str) -> dict[str, Any]:
    """Normalize one compiled administration/control place item.

    Place items intentionally have their own storage path.  The people table
    is constrained to ``office``/``title``/``affiliation`` and must not be
    widened after its immutable migration was published.  Validation still
    uses the shared T01 DTO so the read API cannot grow a second place shape.
    """
    item = dict(_require_object(item, owner))
    item.setdefault("value", None)
    item.setdefault("controller", None)
    item.setdefault("reason_codes", [])
    item["reason_codes"] = _normalize_reason_codes(item["reason_codes"], owner)
    item.setdefault("reason_text", _reason_text(item["reason_codes"]))
    item.setdefault("source_facts", [])
    if not isinstance(item.get("source_facts"), list):
        raise PersistenceError(f"{owner}.source_facts must be an array")
    item.setdefault("evidence_count", 0)
    item.setdefault("evidence_cursor", None)
    _validate_dto("place_state_item", item, owner)
    _require_compiled_item_size(item, owner)
    return item


def _normalize_evidence(evidence: Any, person_owner: str) -> dict[str, list[dict[str, Any]]]:
    """Return ``item_id -> [descriptor, ...]`` for one person."""
    if evidence is None:
        return {}
    evidence = _require_list(evidence, f"{person_owner}.evidence")
    by_item: dict[str, list[dict[str, Any]]] = {}
    for index, entry in enumerate(evidence):
        owner = f"{person_owner}.evidence[{index}]"
        entry = _require_object(entry, owner)
        item_id = _require_text(entry.get("item_id"), f"{owner}.item_id")
        descriptors = _require_list(entry.get("descriptors"), f"{owner}.descriptors")
        normalized: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for position, descriptor in enumerate(descriptors):
            descriptor_owner = f"{owner}.descriptors[{position}]"
            descriptor = dict(_require_object(descriptor, descriptor_owner))
            quote = _require_text(descriptor.get("quote"), f"{descriptor_owner}.quote")
            if not isinstance(descriptor.get("quote_sha256"), str):
                descriptor["quote_sha256"] = hashlib.sha256(quote.encode("utf-8")).hexdigest()
            _validate_dto("evidence_descriptor", descriptor, descriptor_owner)
            descriptor_id = descriptor["descriptor_id"]
            if descriptor_id in seen_ids:
                raise PersistenceError(f"{descriptor_owner} repeats descriptor_id {descriptor_id!r}")
            seen_ids.add(descriptor_id)
            normalized.append(descriptor)
        if item_id in by_item:
            raise PersistenceError(f"{person_owner}.evidence repeats item_id {item_id!r}")
        by_item[item_id] = normalized
    return by_item


def _normalize_person(person: Any, owner: str, unit_phase_mode: str) -> dict[str, Any]:
    person = _require_object(person, owner)
    person_id = _require_text(person.get("person_id"), f"{owner}.person_id")
    name = _require_text(person.get("name"), f"{owner}.name")
    importance = person.get("importance")
    if importance not in IMPORTANCES:
        raise PersistenceError(f"{owner}.importance must be one of {IMPORTANCES}, got {importance!r}")
    certainty = person.get("certainty")
    if certainty not in CERTAINTIES:
        raise PersistenceError(f"{owner}.certainty must be one of {CERTAINTIES}, got {certainty!r}")
    phase_mode = person.get("phase_mode") or unit_phase_mode
    if phase_mode not in PHASE_MODES:
        raise PersistenceError(f"{owner}.phase_mode must be one of {PHASE_MODES}, got {phase_mode!r}")
    reason_codes = _normalize_reason_codes(person.get("reason_codes"), owner)

    raw_items = _require_list(person.get("items", []), f"{owner}.items")
    raw_changes = _require_list(person.get("changes", []), f"{owner}.changes")
    identities = [
        _normalize_identity_item(item, f"{owner}.items[{index}]")
        for index, item in enumerate(raw_items)
    ]
    changes = [
        _normalize_change_item(item, f"{owner}.changes[{index}]")
        for index, item in enumerate(raw_changes)
    ]
    evidence = _normalize_evidence(person.get("evidence"), owner)

    known_items: set[str] = set()
    for index, item in enumerate(identities):
        if item.get("person_id") != person_id:
            raise PersistenceError(f"{owner}.items[{index}].person_id does not match {person_id!r}")
        if item["item_id"] in known_items:
            raise PersistenceError(f"{owner} repeats item_id {item['item_id']!r}")
        known_items.add(item["item_id"])
    for index, item in enumerate(changes):
        if item.get("person_id") != person_id:
            raise PersistenceError(f"{owner}.changes[{index}].person_id does not match {person_id!r}")
        if item["item_id"] in known_items:
            raise PersistenceError(f"{owner} repeats item_id {item['item_id']!r}")
        known_items.add(item["item_id"])

    for item_id in evidence:
        if item_id not in known_items:
            raise PersistenceError(f"{owner}.evidence cites unknown item_id {item_id!r}")

    # The persisted descriptor count is authoritative, not a caller hint.
    for item in identities:
        item["evidence_count"] = len(evidence.get(item["item_id"], []))
        _validate_dto("state_item", item, owner)

    preview_limit = _contract.PersonStateLimits().summary_max_items
    rows: list[dict[str, Any]] = []
    for ordinal, item in enumerate(identities):
        rows.append(
            {
                "item_kind": "identity",
                "item_id": item["item_id"],
                "item_ordinal": ordinal,
                "payload": item,
            }
        )
    for ordinal, item in enumerate(changes):
        rows.append(
            {
                "item_kind": "change",
                "item_id": item["item_id"],
                "item_ordinal": ordinal,
                "payload": item,
            }
        )

    return {
        "person_id": person_id,
        "name": name,
        "importance": importance,
        "importance_rank": 0 if importance == "primary" else 1,
        "phase_mode": phase_mode,
        "certainty": certainty,
        "reason_codes": reason_codes,
        "identity_count": len(identities),
        "change_count": len(changes),
        "preview_identities": identities[:preview_limit],
        "preview_changes": changes[:preview_limit],
        "items": rows,
        "evidence": evidence,
    }


def _normalize_places(
    places: Any, evidence: Any, owner: str
) -> dict[str, Any]:
    """Normalize the flat place projection into stable unit/place indexes."""
    raw_places = _require_list(places, f"{owner}.places")
    place_evidence = _normalize_evidence(evidence, owner)
    normalized: list[dict[str, Any]] = []
    seen_items: set[str] = set()
    for index, raw_item in enumerate(raw_places):
        item_owner = f"{owner}.places[{index}]"
        item = _normalize_place_item(raw_item, item_owner)
        item_id = item["item_id"]
        if item_id in seen_items:
            raise PersistenceError(f"{owner} repeats place item_id {item_id!r}")
        seen_items.add(item_id)
        item["evidence_count"] = len(place_evidence.get(item_id, []))
        _validate_dto("place_state_item", item, item_owner)
        descriptors = place_evidence.get(item_id, [])
        for position, descriptor in enumerate(descriptors):
            _require_compiled_item_size(descriptor, f"{item_owner}.evidence[{position}]")
        # Section 7 bounds the complete item together with its first 16
        # descriptors; later descriptors remain accessible by bounded pages.
        _require_compiled_item_size(
            {"item": item, "descriptors": descriptors[:16]}, item_owner
        )
        normalized.append(item)

    unknown_evidence = sorted(set(place_evidence) - seen_items)
    if unknown_evidence:
        raise PersistenceError(
            f"{owner}.place_evidence cites unknown place item(s): {unknown_evidence}"
        )

    normalized.sort(key=lambda item: (item["place_id"], item["dimension"], item["item_id"]))
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in normalized:
        grouped.setdefault(item["place_id"], []).append(item)

    place_rows: list[dict[str, Any]] = []
    item_rows: list[dict[str, Any]] = []
    for place_ordinal, place_id in enumerate(sorted(grouped)):
        items = grouped[place_id]
        reason_codes = sorted(
            {code for item in items for code in item.get("reason_codes") or []}
        )
        place_rows.append(
            {
                "place_id": place_id,
                "place_ordinal": place_ordinal,
                "name": items[0]["name"],
                "item_count": len(items),
                "administration_count": sum(
                    item["dimension"] == "administration" for item in items
                ),
                "control_count": sum(item["dimension"] == "control" for item in items),
                "certainty": "uncertain"
                if any(item["certainty"] == "uncertain" for item in items)
                else "clear",
                "reason_codes": reason_codes,
                "preview_places": items[: _contract.PersonStateLimits().summary_max_items],
                "items": items,
            }
        )
        for item_ordinal, item in enumerate(items):
            item_rows.append(
                {
                    "place_id": place_id,
                    "item_id": item["item_id"],
                    "item_ordinal": item_ordinal,
                    "payload": item,
                }
            )

    return {
        "places": place_rows,
        "items": item_rows,
        "evidence": place_evidence,
    }


def _normalize_unit(unit: Any, owner: str) -> dict[str, Any]:
    unit = _require_object(unit, owner)
    unit_id = _require_text(unit.get("unit_id"), f"{owner}.unit_id")
    unit_ordinal = unit.get("unit_ordinal")
    if not isinstance(unit_ordinal, int) or isinstance(unit_ordinal, bool) or unit_ordinal < 0:
        raise PersistenceError(f"{owner}.unit_ordinal must be a non-negative integer")
    publication_id = _require_uuid7(unit.get("publication_id"), f"{owner}.publication_id")
    phase_mode = unit.get("phase_mode")
    if phase_mode not in PHASE_MODES:
        raise PersistenceError(f"{owner}.phase_mode must be one of {PHASE_MODES}, got {phase_mode!r}")
    phases = _require_list(unit.get("phases"), f"{owner}.phases")
    normalized_phases: list[dict[str, Any]] = []
    for index, phase in enumerate(phases):
        phase = dict(_require_object(phase, f"{owner}.phases[{index}]"))
        _validate_dto("phase_summary", phase, f"{owner}.phases[{index}]")
        normalized_phases.append(phase)

    people = _require_list(unit.get("people"), f"{owner}.people")
    normalized_people: list[dict[str, Any]] = []
    seen_people: set[str] = set()
    for index, person in enumerate(people):
        normalized = _normalize_person(person, f"{owner}.people[{index}]", phase_mode)
        if normalized["person_id"] in seen_people:
            raise PersistenceError(f"{owner} repeats person_id {normalized['person_id']!r}")
        seen_people.add(normalized["person_id"])
        normalized_people.append(normalized)

    normalized_places = _normalize_places(
        unit.get("places", []), unit.get("place_evidence", []), owner
    )

    return {
        "unit_id": unit_id,
        "unit_ordinal": unit_ordinal,
        "publication_id": publication_id,
        "phase_mode": phase_mode,
        "phases": normalized_phases,
        "people": normalized_people,
        "places": normalized_places["places"],
        "place_items": normalized_places["items"],
        "place_evidence": normalized_places["evidence"],
    }


def _canonical_manifest(normalized: dict[str, Any]) -> dict[str, Any]:
    units = []
    for unit in normalized["units"]:
        canonical_unit = {
            "unit_id": unit["unit_id"],
            "unit_ordinal": unit["unit_ordinal"],
            "publication_id": str(unit["publication_id"]),
            "phase_mode": unit["phase_mode"],
            "phases": unit["phases"],
            "people": [
                {
                    "person_id": person["person_id"],
                    "name": person["name"],
                    "importance": person["importance"],
                    "phase_mode": person["phase_mode"],
                    "certainty": person["certainty"],
                    "reason_codes": person["reason_codes"],
                    "items": [row["payload"] for row in person["items"]],
                    "evidence": [
                        {
                            "item_id": item_id,
                            "descriptors": descriptors,
                        }
                        for item_id, descriptors in person["evidence"].items()
                    ],
                }
                for person in unit["people"]
            ],
        }
        # Keep people-only manifest hashes stable across the additive place
        # migration. Place fields are part of the canonical bytes only when
        # the published unit actually carries place state.
        if unit["place_items"] or unit["place_evidence"]:
            canonical_unit["places"] = [
                row["payload"] for row in unit["place_items"]
            ]
            canonical_unit["place_evidence"] = [
                {"item_id": item_id, "descriptors": descriptors}
                for item_id, descriptors in unit["place_evidence"].items()
            ]
        units.append(canonical_unit)

    return {
        "stream_id": str(normalized["stream_id"]),
        "revision_id": str(normalized["revision_id"]),
        "origin_catalog_sha": normalized["origin_catalog_sha"],
        "compiler_version": normalized["compiler_version"],
        "assessment_hashes": list(normalized["assessment_hashes"]),
        "chapter_publication_ids": [
            str(value) for value in normalized["chapter_publication_ids"]
        ],
        "manifest": normalized["manifest"],
        "units": units,
    }


def _normalize_manifest(conn, manifest: Any) -> dict[str, Any]:
    manifest = _require_object(manifest, "compiled person-state manifest")
    stream_id = _require_uuid7(manifest.get("stream_id"), "manifest stream_id")
    compiler_version = _require_text(
        manifest.get("compiler_version"), "manifest compiler_version"
    )
    stream_row = conn.execute(
        "SELECT revision_id, origin_catalog_sha, chapter_publication_ids"
        " FROM chronicle.reading_streams WHERE stream_id = %s",
        (stream_id,),
    ).fetchone()
    if stream_row is None:
        raise PersistenceConflict(f"manifest stream {stream_id} is not persisted")
    revision_id = _require_uuid(stream_row[0], "stream revision_id")
    origin_catalog_sha = _require_sha(stream_row[1], "stream origin_catalog_sha")
    stream_publications = list(stream_row[2])

    manifest_payload = _require_object(manifest.get("manifest"), "manifest manifest")

    raw_hashes = _require_list(
        manifest.get("assessment_hashes"), "manifest assessment_hashes"
    )
    assessment_hashes: list[str] = []
    for index, value in enumerate(raw_hashes):
        sha = _require_sha(value, f"manifest assessment_hashes[{index}]")
        if sha in assessment_hashes:
            raise PersistenceError(f"manifest repeats assessment_sha {sha}")
        assessment_hashes.append(sha)
    if assessment_hashes:
        persisted = conn.execute(
            "SELECT assessment_sha FROM chronicle.person_state_assessments"
            " WHERE assessment_sha = ANY (%s)",
            (assessment_hashes,),
        ).fetchall()
        known = {row[0] for row in persisted}
        missing = [sha for sha in assessment_hashes if sha not in known]
        if missing:
            raise PersistenceConflict(
                f"manifest cites unpersisted assessments: {missing}"
            )

    raw_publications = manifest.get("chapter_publication_ids")
    if raw_publications is None:
        publications = [
            _require_uuid7(str(value), "stream publication")
            for value in stream_publications
        ]
    else:
        raw_publications = _require_list(
            raw_publications, "manifest chapter_publication_ids"
        )
        publications = [
            _require_uuid7(value, f"manifest chapter_publication_ids[{index}]")
            for index, value in enumerate(raw_publications)
        ]
    if set(publications) != set(stream_publications):
        raise PersistenceConflict(
            "manifest chapter_publication_ids must exactly match the stream's publications"
        )
    publication_set = set(publications)

    raw_units = _require_list(manifest.get("units"), "manifest units")
    units: list[dict[str, Any]] = []
    seen_units: set[str] = set()
    for index, unit in enumerate(raw_units):
        normalized = _normalize_unit(unit, f"manifest.units[{index}]")
        if normalized["unit_id"] in seen_units:
            raise PersistenceError(f"manifest repeats unit_id {normalized['unit_id']!r}")
        seen_units.add(normalized["unit_id"])
        units.append(normalized)

    unit_rows = conn.execute(
        "SELECT unit_id, ordinal, publication_id FROM chronicle.reading_units"
        " WHERE stream_id = %s",
        (stream_id,),
    ).fetchall()
    by_unit = {row[0]: (int(row[1]), row[2]) for row in unit_rows}
    for unit in units:
        known = by_unit.get(unit["unit_id"])
        if known is None:
            raise PersistenceConflict(
                f"manifest unit {unit['unit_id']!r} is not part of stream {stream_id}"
            )
        if known[0] != unit["unit_ordinal"] or known[1] != unit["publication_id"]:
            raise PersistenceConflict(
                f"manifest unit {unit['unit_id']!r} ordinal/publication does not match the stream"
            )
        for person in unit["people"]:
            for row in person["items"]:
                for source_fact in row["payload"].get("source_facts") or []:
                    chapter_publication_id = source_fact.get("chapter_publication_id")
                    try:
                        parsed = _require_uuid(
                            chapter_publication_id, "source_fact chapter_publication_id"
                        )
                    except PersistenceError as exc:
                        raise PersistenceConflict(
                            f"manifest item {row['item_id']!r} source fact is not bound to a "
                            "chapter publication"
                        ) from exc
                    if parsed not in publication_set:
                        raise PersistenceConflict(
                            f"manifest item {row['item_id']!r} cites publication {parsed} "
                            "outside the stream snapshot"
                        )
        for row in unit["place_items"]:
            for source_fact in row["payload"].get("source_facts") or []:
                chapter_publication_id = source_fact.get("chapter_publication_id")
                try:
                    parsed = _require_uuid(
                        chapter_publication_id, "place source_fact chapter_publication_id"
                    )
                except PersistenceError as exc:
                    raise PersistenceConflict(
                        f"place item {row['item_id']!r} source fact is not bound to a "
                        "chapter publication"
                    ) from exc
                if parsed not in publication_set:
                    raise PersistenceConflict(
                        f"place item {row['item_id']!r} cites publication {parsed} "
                        "outside the stream snapshot"
                    )
        for item_id, descriptors in unit["place_evidence"].items():
            for descriptor in descriptors:
                try:
                    parsed = _require_uuid(
                        descriptor.get("source_publication_id"),
                        "place evidence source_publication_id",
                    )
                except PersistenceError as exc:
                    raise PersistenceConflict(
                        f"place item {item_id!r} evidence is not bound to a chapter publication"
                    ) from exc
                if parsed not in publication_set:
                    raise PersistenceConflict(
                        f"place item {item_id!r} evidence cites publication {parsed} "
                        "outside the stream snapshot"
                    )
        _require_place_evidence_page_sizes(
            unit, stream_id=stream_id, catalog_sha=origin_catalog_sha
        )

    unit_phases = {
        unit["unit_id"]: {"phase_mode": unit["phase_mode"], "phases": unit["phases"]}
        for unit in units
    }

    normalized = {
        "stream_id": stream_id,
        "revision_id": revision_id,
        "origin_catalog_sha": origin_catalog_sha,
        "compiler_version": compiler_version,
        "assessment_hashes": assessment_hashes,
        "chapter_publication_ids": publications,
        "manifest": manifest_payload,
        "units": units,
        "unit_phases": unit_phases,
    }
    normalized["manifest_sha"] = sha256_json(_canonical_manifest(normalized))
    return normalized


# ---------------------------------------------------------------------------
# Assessment validation
# ---------------------------------------------------------------------------


def _normalize_assessment(conn, assessment: Any, owner: str) -> dict[str, Any]:
    assessment = _require_object(assessment, owner)
    plan_fingerprint = _require_sha(
        assessment.get("plan_fingerprint"), f"{owner}.plan_fingerprint"
    )
    base_catalog_sha = _require_sha(
        assessment.get("base_catalog_sha"), f"{owner}.base_catalog_sha"
    )
    compiler_version = _require_text(assessment.get("compiler_version"), f"{owner}.compiler_version")
    payload = _require_object(assessment.get("payload"), f"{owner}.payload")
    computed = sha256_json(payload)
    supplied = assessment.get("assessment_sha")
    if supplied is not None and supplied != computed:
        raise PersistenceError(
            f"{owner}.assessment_sha does not match the payload bytes"
        )
    exists = conn.execute(
        "SELECT 1 FROM chronicle.canonical_catalogs WHERE artifact_sha256 = %s",
        (base_catalog_sha,),
    ).fetchone()
    if exists is None:
        raise PersistenceConflict(f"{owner}.base_catalog_sha {base_catalog_sha} is not persisted")
    return {
        "assessment_sha": computed,
        "plan_fingerprint": plan_fingerprint,
        "base_catalog_sha": base_catalog_sha,
        "compiler_version": compiler_version,
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# Disagreement validation
# ---------------------------------------------------------------------------


def _normalize_disagreement(record: Any, owner: str) -> dict[str, Any]:
    record = _require_object(record, owner)
    disagreement_id = _require_text(record.get("disagreement_id"), f"{owner}.disagreement_id")
    if not re.match(r"^psd_[0-9a-f]{24}$", disagreement_id):
        raise PersistenceError(f"{owner}.disagreement_id must look like psd_<24 hex>, got {disagreement_id!r}")
    topic = _require_text(record.get("topic"), f"{owner}.topic")
    raw_facts = _require_list(record.get("fact_refs"), f"{owner}.fact_refs")
    fact_refs: list[str] = []
    for fact_ref in raw_facts:
        if not isinstance(fact_ref, str) or not fact_ref:
            raise PersistenceError(f"{owner}.fact_refs carries invalid ref {fact_ref!r}")
        if fact_ref not in fact_refs:
            fact_refs.append(fact_ref)
    if len(fact_refs) < 2:
        raise PersistenceError(f"{owner}.fact_refs requires at least two distinct refs")
    phase_ids = [
        _require_phase_id(value, f"{owner}.phase_ids")
        for value in _require_list(record.get("phase_ids", []), f"{owner}.phase_ids")
    ]
    reason_codes = _normalize_reason_codes(record.get("reason_codes"), owner)
    raw_sources = _require_list(record.get("sources", []), f"{owner}.sources")
    sources: list[dict[str, Any]] = []
    source_keys: list[str] = []
    for index, source in enumerate(raw_sources):
        source_owner = f"{owner}.sources[{index}]"
        source = _require_object(source, source_owner)
        fact_ref = _require_text(source.get("fact_ref"), f"{source_owner}.fact_ref")
        if fact_ref not in fact_refs:
            raise PersistenceError(
                f"{source_owner}.fact_ref {fact_ref!r} is not one of this disagreement's fact_refs"
            )
        chapter_id = _require_text(source.get("chapter_id"), f"{source_owner}.chapter_id")
        entry: dict[str, Any] = {"fact_ref": fact_ref, "chapter_id": chapter_id}
        for field in ("stream_id", "unit_id", "publication_id"):
            value = source.get(field)
            if value is not None:
                entry[field] = str(value)
        if isinstance(source.get("claim_refs"), list):
            entry["claim_refs"] = [ref for ref in source["claim_refs"] if isinstance(ref, str)]
        if isinstance(source.get("anchor_ids"), list):
            entry["anchor_ids"] = [ref for ref in source["anchor_ids"] if isinstance(ref, str)]
        sources.append(entry)
        key = f"{chapter_id}:{fact_ref}"
        if key not in source_keys:
            source_keys.append(key)
    payload = {
        "disagreement_id": disagreement_id,
        "topic": topic,
        "fact_refs": fact_refs,
        "phase_ids": phase_ids,
        "reason_codes": reason_codes,
        "sources": sources,
    }
    return {
        "disagreement_id": disagreement_id,
        "topic": topic,
        "fact_refs": fact_refs,
        "phase_ids": phase_ids,
        "reason_codes": reason_codes,
        "source_keys": source_keys,
        "sources": sources,
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# Write entries (caller owns the transaction; no commit, no lease)
# ---------------------------------------------------------------------------


def persist_person_state_assessments(conn, assessments: Any) -> list[str]:
    """Persist immutable assessment artifacts inside the caller's transaction.

    Accepts one artifact object or a list. The stable key is
    ``plan_fingerprint``: replaying the same plan with the same payload returns
    the same ``assessment_sha``, and the same plan with different bytes raises
    :class:`PersistenceConflict`.
    """
    if isinstance(assessments, dict):
        assessments = [assessments]
    entries = _require_list(assessments, "person-state assessments")
    normalized = [
        _normalize_assessment(conn, entry, f"person-state assessments[{index}]")
        for index, entry in enumerate(entries)
    ]
    result: list[str] = []
    for entry in normalized:
        existing = conn.execute(
            "SELECT assessment_sha, base_catalog_sha, compiler_version"
            " FROM chronicle.person_state_assessments WHERE plan_fingerprint = %s",
            (entry["plan_fingerprint"],),
        ).fetchone()
        if existing is not None:
            if (
                existing[0] == entry["assessment_sha"]
                and existing[1] == entry["base_catalog_sha"]
                and existing[2] == entry["compiler_version"]
            ):
                result.append(existing[0])
                continue
            raise PersistenceConflict(
                f"immutable_assessment_conflict: plan {entry['plan_fingerprint']} already has "
                "different assessment bytes"
            )
        try:
            with conn.transaction(savepoint_name="person_state_assessment_insert"):
                conn.execute(
                    """
                    INSERT INTO chronicle.person_state_assessments(
                        assessment_sha, plan_fingerprint, base_catalog_sha,
                        compiler_version, payload
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        entry["assessment_sha"],
                        entry["plan_fingerprint"],
                        entry["base_catalog_sha"],
                        entry["compiler_version"],
                        Jsonb(entry["payload"]),
                    ),
                )
        except Exception as exc:  # noqa: BLE001 - race recovery below
            from psycopg import errors as _errors

            if isinstance(exc, _errors.UniqueViolation):
                row = conn.execute(
                    "SELECT assessment_sha, base_catalog_sha, compiler_version"
                    " FROM chronicle.person_state_assessments WHERE plan_fingerprint = %s",
                    (entry["plan_fingerprint"],),
                ).fetchone()
                if row is not None and row[0] == entry["assessment_sha"]:
                    result.append(row[0])
                    continue
                raise PersistenceConflict(
                    f"immutable_assessment_conflict: plan {entry['plan_fingerprint']} "
                    "raced with different bytes"
                ) from exc
            raise
        result.append(entry["assessment_sha"])
    return result


def persist_person_state_manifest(conn, manifest: dict[str, Any]) -> str:
    """Persist one compiled state manifest plus its bounded per-unit index.

    The caller already holds the unique publish transaction; this function never
    opens or commits a transaction. Replaying the complete normalized input for
    a stream returns the same ``manifest_sha`` with no new rows; different bytes
    for an already-published stream raise :class:`PersistenceConflict`.
    """
    normalized = _normalize_manifest(conn, manifest)
    stream_id = normalized["stream_id"]
    manifest_sha = normalized["manifest_sha"]

    existing = conn.execute(
        "SELECT manifest_sha, manifest FROM chronicle.person_state_manifests"
        " WHERE stream_id = %s",
        (stream_id,),
    ).fetchone()
    if existing is not None:
        if existing[0] == manifest_sha and existing[1] == normalized["manifest"]:
            return existing[0]
        raise PersistenceConflict(
            f"immutable_state_manifest_conflict: stream {stream_id} already has state "
            f"manifest {existing[0]} with different compiled bytes"
        )

    try:
        with conn.transaction(savepoint_name="person_state_manifest_insert"):
            conn.execute(
                """
                INSERT INTO chronicle.person_state_manifests(
                    manifest_sha, stream_id, revision_id, origin_catalog_sha,
                    compiler_version, assessment_hashes, chapter_publication_ids,
                    unit_phases, manifest
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    manifest_sha,
                    stream_id,
                    normalized["revision_id"],
                    normalized["origin_catalog_sha"],
                    normalized["compiler_version"],
                    normalized["assessment_hashes"],
                    normalized["chapter_publication_ids"],
                    Jsonb(normalized["unit_phases"]),
                    Jsonb(normalized["manifest"]),
                ),
            )
            for unit in normalized["units"]:
                _insert_unit(conn, manifest_sha=manifest_sha, stream_id=stream_id, unit=unit)
    except Exception as exc:  # noqa: BLE001 - race recovery below
        from psycopg import errors as _errors

        if isinstance(exc, _errors.UniqueViolation):
            row = conn.execute(
                "SELECT manifest_sha, manifest FROM chronicle.person_state_manifests"
                " WHERE stream_id = %s",
                (stream_id,),
            ).fetchone()
            if row is not None and row[0] == manifest_sha and row[1] == normalized["manifest"]:
                return row[0]
            raise PersistenceConflict(
                f"immutable_state_manifest_conflict: stream {stream_id} is already "
                "published with different compiled bytes"
            ) from exc
        raise
    return manifest_sha


def _insert_unit(conn, *, manifest_sha: str, stream_id: uuid.UUID, unit: dict[str, Any]) -> None:
    for person in unit["people"]:
        conn.execute(
            """
            INSERT INTO chronicle.person_state_unit_people(
                manifest_sha, stream_id, unit_id, person_id, unit_ordinal, name,
                importance, importance_rank, phase_mode, certainty, reason_codes,
                phases, identity_count, change_count, preview_identities,
                preview_changes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                manifest_sha,
                stream_id,
                unit["unit_id"],
                person["person_id"],
                unit["unit_ordinal"],
                person["name"],
                person["importance"],
                person["importance_rank"],
                person["phase_mode"],
                person["certainty"],
                person["reason_codes"],
                Jsonb(unit["phases"]),
                person["identity_count"],
                person["change_count"],
                Jsonb(person["preview_identities"]),
                Jsonb(person["preview_changes"]),
            ),
        )
        for row in person["items"]:
            _insert_item(
                conn,
                manifest_sha=manifest_sha,
                stream_id=stream_id,
                unit_id=unit["unit_id"],
                person_id=person["person_id"],
                row=row,
            )
        for item_id, descriptors in person["evidence"].items():
            for ordinal, descriptor in enumerate(descriptors):
                conn.execute(
                    """
                    INSERT INTO chronicle.person_state_item_evidence(
                        manifest_sha, stream_id, unit_id, item_id,
                        descriptor_ordinal, descriptor_id, source_publication_id,
                        anchor_id, quote, quote_sha256, attribution, source_title,
                        phase_id, relation
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        manifest_sha,
                        stream_id,
                        unit["unit_id"],
                        item_id,
                        ordinal,
                        descriptor["descriptor_id"],
                        _require_uuid(descriptor["source_publication_id"], "descriptor source_publication_id"),
                        descriptor["anchor_id"],
                        descriptor["quote"],
                        descriptor["quote_sha256"],
                        descriptor["attribution"],
                        descriptor["source_title"],
                        descriptor["phase_id"],
                        descriptor["relation"],
                    ),
                )

    for place in unit["places"]:
        conn.execute(
            """
            INSERT INTO chronicle.person_state_unit_places(
                manifest_sha, stream_id, unit_id, place_id, place_ordinal, name,
                item_count, administration_count, control_count, certainty,
                reason_codes, phases, preview_places
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                manifest_sha,
                stream_id,
                unit["unit_id"],
                place["place_id"],
                place["place_ordinal"],
                place["name"],
                place["item_count"],
                place["administration_count"],
                place["control_count"],
                place["certainty"],
                place["reason_codes"],
                Jsonb(unit["phases"]),
                Jsonb(place["preview_places"]),
            ),
        )

    for row in unit["place_items"]:
        _insert_place_item(
            conn,
            manifest_sha=manifest_sha,
            stream_id=stream_id,
            unit_id=unit["unit_id"],
            row=row,
        )

    for item_id, descriptors in unit["place_evidence"].items():
        for ordinal, descriptor in enumerate(descriptors):
            conn.execute(
                """
                INSERT INTO chronicle.person_state_place_item_evidence(
                    manifest_sha, stream_id, unit_id, place_id, item_id,
                    descriptor_ordinal, descriptor_id, source_publication_id,
                    anchor_id, quote, quote_sha256, attribution, source_title,
                    phase_id, relation
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    manifest_sha,
                    stream_id,
                    unit["unit_id"],
                    next(
                        row["place_id"]
                        for row in unit["place_items"]
                        if row["item_id"] == item_id
                    ),
                    item_id,
                    ordinal,
                    descriptor["descriptor_id"],
                    _require_uuid(
                        descriptor["source_publication_id"],
                        "place descriptor source_publication_id",
                    ),
                    descriptor["anchor_id"],
                    descriptor["quote"],
                    descriptor["quote_sha256"],
                    descriptor["attribution"],
                    descriptor["source_title"],
                    descriptor["phase_id"],
                    descriptor["relation"],
                ),
            )


def _insert_item(
    conn,
    *,
    manifest_sha: str,
    stream_id: uuid.UUID,
    unit_id: str,
    person_id: str,
    row: dict[str, Any],
) -> None:
    payload = row["payload"]
    conn.execute(
        """
        INSERT INTO chronicle.person_state_items(
            manifest_sha, stream_id, unit_id, person_id, item_kind, item_id,
            dimension, value, relation, target, target_id, qualification,
            certainty, reason_codes, reason_text, phase_ids, current, operation,
            from_phase_id, to_phase_id, source_facts, evidence_count,
            item_ordinal, payload
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            manifest_sha,
            stream_id,
            unit_id,
            person_id,
            row["item_kind"],
            row["item_id"],
            payload["dimension"],
            payload.get("value"),
            payload.get("relation"),
            payload.get("target"),
            payload.get("target_id"),
            payload.get("qualification", "ordinary"),
            payload["certainty"],
            payload["reason_codes"],
            payload.get("reason_text", ""),
            payload.get("phase_ids", []) or [],
            payload.get("current"),
            payload.get("operation"),
            payload.get("from_phase_id"),
            payload.get("to_phase_id"),
            Jsonb(payload.get("source_facts", [])),
            int(payload.get("evidence_count", 0)),
            row["item_ordinal"],
            Jsonb(payload),
        ),
    )


def _insert_place_item(
    conn,
    *,
    manifest_sha: str,
    stream_id: uuid.UUID,
    unit_id: str,
    row: dict[str, Any],
) -> None:
    payload = row["payload"]
    conn.execute(
        """
        INSERT INTO chronicle.person_state_place_items(
            manifest_sha, stream_id, unit_id, place_id, item_id, dimension,
            value, controller, certainty, reason_codes, reason_text, phase_ids,
            current, source_facts, evidence_count, item_ordinal, payload
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s)
        """,
        (
            manifest_sha,
            stream_id,
            unit_id,
            row["place_id"],
            row["item_id"],
            payload["dimension"],
            payload.get("value"),
            payload.get("controller"),
            payload["certainty"],
            payload["reason_codes"],
            payload.get("reason_text", ""),
            payload.get("phase_ids", []) or [],
            payload["current"],
            Jsonb(payload.get("source_facts", [])),
            int(payload.get("evidence_count", 0)),
            row["item_ordinal"],
            Jsonb(payload),
        ),
    )


def persist_person_state_disagreements(conn, disagreements: dict[str, Any]) -> list[str]:
    """Persist an immutable, catalog-scoped disagreement index in the caller's
    transaction. Replaying identical records is a no-op; a different payload for
    an existing ``(catalog_sha, disagreement_id)`` raises
    :class:`PersistenceConflict`.
    """
    envelope = _require_object(disagreements, "person-state disagreements")
    catalog_sha = _require_sha(envelope.get("catalog_sha"), "disagreements catalog_sha")
    compiler_version = _require_text(
        envelope.get("compiler_version"), "disagreements compiler_version"
    )
    exists = conn.execute(
        "SELECT 1 FROM chronicle.canonical_catalogs WHERE artifact_sha256 = %s",
        (catalog_sha,),
    ).fetchone()
    if exists is None:
        raise PersistenceConflict(f"disagreements catalog {catalog_sha} is not persisted")
    raw_records = _require_list(
        envelope.get("disagreements"), "disagreements disagreements"
    )
    records = [
        _normalize_disagreement(record, f"disagreements[{index}]")
        for index, record in enumerate(raw_records)
    ]
    result: list[str] = []
    for record in records:
        existing = conn.execute(
            "SELECT payload FROM chronicle.person_state_disagreements"
            " WHERE catalog_sha = %s AND disagreement_id = %s",
            (catalog_sha, record["disagreement_id"]),
        ).fetchone()
        if existing is not None:
            if existing[0] == record["payload"]:
                result.append(record["disagreement_id"])
                continue
            raise PersistenceConflict(
                f"immutable_disagreement_conflict: {record['disagreement_id']} already has "
                "different bytes"
            )
        try:
            with conn.transaction(savepoint_name="person_state_disagreement_insert"):
                conn.execute(
                    """
                    INSERT INTO chronicle.person_state_disagreements(
                        disagreement_id, catalog_sha, compiler_version, topic,
                        fact_refs, phase_ids, reason_codes, source_keys, sources,
                        payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record["disagreement_id"],
                        catalog_sha,
                        compiler_version,
                        record["topic"],
                        record["fact_refs"],
                        record["phase_ids"],
                        record["reason_codes"],
                        record["source_keys"],
                        Jsonb(record["sources"]),
                        Jsonb(record["payload"]),
                    ),
                )
        except Exception as exc:  # noqa: BLE001 - race recovery below
            from psycopg import errors as _errors

            if isinstance(exc, _errors.UniqueViolation):
                row = conn.execute(
                    "SELECT payload FROM chronicle.person_state_disagreements"
                    " WHERE catalog_sha = %s AND disagreement_id = %s",
                    (catalog_sha, record["disagreement_id"]),
                ).fetchone()
                if row is not None and row[0] == record["payload"]:
                    result.append(record["disagreement_id"])
                    continue
                raise PersistenceConflict(
                    f"immutable_disagreement_conflict: {record['disagreement_id']} raced "
                    "with different bytes"
                ) from exc
            raise
        result.append(record["disagreement_id"])
    return result


# ---------------------------------------------------------------------------
# Snapshot visibility (catalog sequence range)
# ---------------------------------------------------------------------------


def _snapshot_sequence(conn, catalog_sha: Any) -> int:
    catalog_sha = _require_sha(catalog_sha, "snapshot catalog_sha")
    row = conn.execute(
        "SELECT publication_sequence FROM chronicle.canonical_catalogs"
        " WHERE artifact_sha256 = %s",
        (catalog_sha,),
    ).fetchone()
    if row is None:
        raise PersistenceError(f"unknown snapshot catalog {catalog_sha}")
    return int(row[0])


def _require_visible_manifest(conn, *, stream_id: uuid.UUID, catalog_sha: str) -> int:
    snapshot_sequence = _snapshot_sequence(conn, catalog_sha)
    row = conn.execute(
        """
        SELECT origin.publication_sequence
        FROM chronicle.person_state_manifests m
        JOIN chronicle.canonical_catalogs origin
          ON origin.artifact_sha256 = m.origin_catalog_sha
        WHERE m.stream_id = %s
        """,
        (stream_id,),
    ).fetchone()
    if row is None:
        raise PersistenceError(f"unknown person-state manifest for stream {stream_id}")
    if int(row[0]) > snapshot_sequence:
        raise PersistenceError(
            f"person-state manifest for stream {stream_id} is not visible in snapshot {catalog_sha}"
        )
    return snapshot_sequence


def _manifest_metadata(conn, *, stream_id: uuid.UUID, unit_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT m.manifest_sha, m.origin_catalog_sha, m.unit_phases,
               u.publication_id, u.ordinal
        FROM chronicle.person_state_manifests m
        JOIN chronicle.reading_units u
          ON u.stream_id = m.stream_id AND u.unit_id = %s
        WHERE m.stream_id = %s
        """,
        (unit_id, stream_id),
    ).fetchone()
    if row is None:
        raise PersistenceError(
            f"unknown person-state manifest for stream {stream_id} unit {unit_id}"
        )
    unit_phases = row[2] if isinstance(row[2], dict) else {}
    phase_info = unit_phases.get(unit_id)
    if not isinstance(phase_info, dict):
        # The manifest for this stream does not cover the addressed reading unit.
        # An empty page would look like "no recorded state" and hide a missing
        # compiled unit, so the read fails closed for the caller to surface 409.
        raise PersistenceError(
            f"person-state manifest for stream {stream_id} does not cover unit {unit_id}"
        )
    return {
        "manifest_sha": row[0],
        "origin_catalog_sha": row[1],
        "publication_id": str(row[3]),
        "unit_ordinal": int(row[4]),
        "phase_mode": phase_info.get("phase_mode", "unknown"),
        "phases": phase_info.get("phases", []),
    }


def _require_catalog(conn, catalog_sha: Any) -> str:
    catalog_sha = _require_sha(catalog_sha, "catalog_sha")
    row = conn.execute(
        "SELECT 1 FROM chronicle.canonical_catalogs WHERE artifact_sha256 = %s",
        (catalog_sha,),
    ).fetchone()
    if row is None:
        raise PersistenceError(f"unknown catalog {catalog_sha}")
    return catalog_sha


def _require_unit_person(
    conn, *, stream_id: uuid.UUID, unit_id: str, person_id: str
) -> None:
    row = conn.execute(
        """
        SELECT 1 FROM chronicle.person_state_unit_people
        WHERE stream_id = %s AND unit_id = %s AND person_id = %s
        """,
        (stream_id, unit_id, person_id),
    ).fetchone()
    if row is None:
        raise PersistenceError(
            f"unknown person {person_id!r} in stream {stream_id} unit {unit_id}"
        )


def _require_unit_place(
    conn, *, stream_id: uuid.UUID, unit_id: str, place_id: str
) -> None:
    row = conn.execute(
        """
        SELECT 1 FROM chronicle.person_state_unit_places
        WHERE stream_id = %s AND unit_id = %s AND place_id = %s
        """,
        (stream_id, unit_id, place_id),
    ).fetchone()
    if row is None:
        # A typed context place can legitimately have no recorded state, so
        # there is no item-derived summary row. Check this exact reading unit,
        # not another unit or the whole chapter, before allowing an empty page.
        row = conn.execute(
            """
            SELECT 1 FROM chronicle.reading_units
            WHERE stream_id = %s AND unit_id = %s AND context_entities @> %s
            """,
            (stream_id, unit_id, Jsonb([{"canonical_id": place_id, "kind": "place"}])),
        ).fetchone()
    if row is None:
        raise PersistenceError(
            f"unknown place {place_id!r} in stream {stream_id} unit {unit_id}"
        )


def _bound_phase_ids(meta: dict[str, Any]) -> set[str]:
    return {
        phase.get("phase_id")
        for phase in meta.get("phases", [])
        if isinstance(phase, dict) and isinstance(phase.get("phase_id"), str)
    }


def _require_bound_phase(meta: dict[str, Any], phase_id: str) -> None:
    if phase_id not in _bound_phase_ids(meta):
        raise PersistenceError(
            f"phase {phase_id!r} is not bound to this unit's person-state manifest"
        )


# ---------------------------------------------------------------------------
# Cursor helpers (scope-bound opaque keysets)
# ---------------------------------------------------------------------------


def _encode_cursor(scope: dict[str, Any], after: Any) -> str:
    """Encode an opaque cursor carrying its complete read scope.

    The scope names every dimension that changes the result set
    (kind/stream/unit/person/section/phase/catalog/manifest/item); decoding
    rejects a cursor whose scope does not match the current request.
    """
    payload = {"v": CURSOR_VERSION, "after": after, **scope}
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: Any, scope: dict[str, Any], description: str = "cursor") -> Any:
    if not isinstance(cursor, str) or not cursor:
        raise PersonStateCursorError(f"{description} must be a non-empty string")
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise PersonStateCursorError(f"{description} is not a valid cursor") from exc
    if not isinstance(payload, dict) or payload.get("v") != CURSOR_VERSION:
        raise PersonStateCursorError(f"{description} is not a valid cursor")
    if payload.get("kind") != scope.get("kind"):
        raise PersonStateCursorError(
            f"{description} belongs to another person-state scope"
        )
    for key, value in scope.items():
        if payload.get(key) != value:
            raise PersonStateCursorError(
                f"{description} is bound to a different person-state {key} scope"
            )
    return payload.get("after")


def _cursor_ordinal(after: Any, description: str = "cursor") -> int:
    if not isinstance(after, int) or isinstance(after, bool) or after < 0:
        raise PersonStateCursorError(
            f"{description} must carry a non-negative integer position"
        )
    return after


def _cursor_person_rank(after: Any, description: str = "cursor") -> tuple[int, str]:
    if (
        not isinstance(after, list)
        or len(after) != 2
        or not isinstance(after[0], int)
        or isinstance(after[0], bool)
        or after[0] not in (0, 1)
        or not isinstance(after[1], str)
        or not after[1]
    ):
        raise PersonStateCursorError(
            f"{description} must carry an (importance_rank, person_id) position"
        )
    return after[0], after[1]


def _cursor_place_position(
    after: Any, description: str = "cursor"
) -> tuple[str, int, str]:
    if (
        not isinstance(after, list)
        or len(after) != 3
        or not isinstance(after[0], str)
        or not after[0]
        or not isinstance(after[1], int)
        or isinstance(after[1], bool)
        or after[1] < 0
        or not isinstance(after[2], str)
        or not after[2]
    ):
        raise PersonStateCursorError(
            f"{description} must carry a (place_id, item_ordinal, item_id) position"
        )
    return after[0], after[1], after[2]


def _cursor_text(after: Any, description: str = "cursor") -> str:
    if not isinstance(after, str) or not after:
        raise PersonStateCursorError(f"{description} must carry a string position")
    return after


def _normalize_limit(limit: Any, *, maximum: int = 50, description: str = "limit") -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > maximum:
        raise PersistenceError(f"{description} must be an integer between 1 and {maximum}")
    return limit


def _require_item_id(value: Any, description: str = "item_id") -> str:
    text = _require_text(value, description)
    if not _ITEM_ID_RE.match(text):
        raise PersistenceError(f"{description} must look like psi_<24 hex>, got {text!r}")
    return text


# ---------------------------------------------------------------------------
# Disagreement overlay (only ever adds recorded uncertainty)
# ---------------------------------------------------------------------------


def _overlay_catalog_disagreements(
    conn, *, catalog_sha: str | None, rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    if catalog_sha is None or not rows:
        return rows
    page_keys: set[str] = set()
    row_keys: list[list[str]] = []
    for row in rows:
        keys = _source_keys(row)
        row_keys.append(keys)
        page_keys.update(keys)
    if not page_keys:
        return rows
    found = conn.execute(
        "SELECT source_keys FROM chronicle.person_state_disagreements"
        " WHERE catalog_sha = %s AND source_keys && %s",
        (catalog_sha, sorted(page_keys)),
    ).fetchall()
    disagreeing: set[str] = set()
    for found_row in found:
        for key in found_row[0] or []:
            if key in page_keys:
                disagreeing.add(key)
    if not disagreeing:
        return rows
    overlaid: list[dict[str, str]] = []
    for row, keys in zip(rows, row_keys):
        if any(key in disagreeing for key in keys):
            row = _mark_disagreement(row)
        overlaid.append(row)
    return overlaid


def _source_keys(row: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for source_fact in row.get("source_facts") or []:
        if not isinstance(source_fact, dict):
            continue
        chapter_id = source_fact.get("chapter_id")
        fact_ref = source_fact.get("fact_ref")
        if isinstance(chapter_id, str) and isinstance(fact_ref, str):
            keys.append(f"{chapter_id}:{fact_ref}")
    return keys


def _mark_disagreement(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    codes = set(row.get("reason_codes") or [])
    codes.add("source_disagreement")
    row["reason_codes"] = sorted(code for code in codes if code in REASON_CODES)
    row["certainty"] = "uncertain"
    if "reason_text" in row:
        row["reason_text"] = _reason_text(row["reason_codes"])
    return row


# ---------------------------------------------------------------------------
# SELECT-only bounded reads
# ---------------------------------------------------------------------------


def list_unit_people(
    conn,
    *,
    stream_id: uuid.UUID,
    unit_id: str,
    catalog_sha: str | None = None,
    limit: int = 6,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return one bounded page of per-unit person summaries."""
    stream_id = _require_uuid(stream_id, "stream_id")
    unit_id = _require_text(unit_id, "unit_id")
    limit = _normalize_limit(limit, maximum=50)
    meta = _manifest_metadata(conn, stream_id=stream_id, unit_id=unit_id)
    if catalog_sha is not None:
        _require_visible_manifest(conn, stream_id=stream_id, catalog_sha=catalog_sha)
    # The omitted catalog means the stream's own origin snapshot. Normalize it
    # once so the cursor scope, the response and the overlay all agree.
    effective_catalog_sha = catalog_sha or meta["origin_catalog_sha"]

    scope = {
        "kind": "unit_people",
        "stream_id": str(stream_id),
        "unit_id": unit_id,
        "catalog_sha": effective_catalog_sha,
        "manifest_sha": meta["manifest_sha"],
    }
    clauses = ["stream_id = %s", "unit_id = %s"]
    params: list[Any] = [stream_id, unit_id]
    if cursor is not None:
        rank, cursor_person = _cursor_person_rank(_decode_cursor(cursor, scope))
        clauses.append("(importance_rank, person_id) > (%s, %s)")
        params.extend([rank, cursor_person])
    rows = conn.execute(
        f"""
        SELECT person_id, name, importance, phase_mode, certainty, reason_codes,
               identity_count, change_count, preview_identities, preview_changes
        FROM chronicle.person_state_unit_people
        WHERE {' AND '.join(clauses)}
        ORDER BY importance_rank, person_id
        LIMIT %s
        """,
        (*params, limit + 1),
    ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    people = [
        _person_summary(
            row,
            manifest_sha=meta["manifest_sha"],
            stream_id=stream_id,
            unit_id=unit_id,
            catalog_sha=effective_catalog_sha,
        )
        for row in rows
    ]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _encode_cursor(
            scope, [0 if last[2] == "primary" else 1, last[0]]
        )
    return {
        "stream_id": str(stream_id),
        "unit_id": unit_id,
        "catalog_sha": effective_catalog_sha,
        "publication_id": meta["publication_id"],
        "state_manifest_sha": meta["manifest_sha"],
        "phase_mode": meta["phase_mode"],
        "phases": list(meta["phases"]),
        "limit": limit,
        "people": people,
        "people_count": len(people),
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def list_unit_places(
    conn,
    *,
    stream_id: uuid.UUID,
    unit_id: str,
    place_id: str | None = None,
    phase_id: str | None = None,
    catalog_sha: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return a bounded page of a unit's administration/control place items."""
    stream_id = _require_uuid(stream_id, "stream_id")
    unit_id = _require_text(unit_id, "unit_id")
    if place_id is not None:
        place_id = _require_text(place_id, "place_id")
    if phase_id is not None:
        phase_id = _require_phase_id(phase_id, "phase_id")
    limit = _normalize_limit(limit, maximum=50)
    meta = _manifest_metadata(conn, stream_id=stream_id, unit_id=unit_id)
    if catalog_sha is not None:
        _require_visible_manifest(conn, stream_id=stream_id, catalog_sha=catalog_sha)
    if place_id is not None:
        _require_unit_place(
            conn, stream_id=stream_id, unit_id=unit_id, place_id=place_id
        )
    if phase_id is not None:
        _require_bound_phase(meta, phase_id)
    effective_catalog_sha = catalog_sha or meta["origin_catalog_sha"]

    scope = {
        "kind": "unit_places",
        "stream_id": str(stream_id),
        "unit_id": unit_id,
        "place_id": place_id,
        "phase_id": phase_id,
        "catalog_sha": effective_catalog_sha,
        "manifest_sha": meta["manifest_sha"],
    }
    clauses = ["stream_id = %s", "unit_id = %s"]
    params: list[Any] = [stream_id, unit_id]
    if place_id is not None:
        clauses.append("place_id = %s")
        params.append(place_id)
    if phase_id is not None:
        clauses.append("%s = ANY (phase_ids)")
        params.append(phase_id)
    if cursor is not None:
        after_place, after_ordinal, after_item = _cursor_place_position(
            _decode_cursor(cursor, scope)
        )
        clauses.append("(place_id, item_ordinal, item_id) > (%s, %s, %s)")
        params.extend([after_place, after_ordinal, after_item])
    rows = conn.execute(
        f"""
        SELECT place_id, item_id, item_ordinal, payload
        FROM chronicle.person_state_place_items
        WHERE {' AND '.join(clauses)}
        ORDER BY place_id, item_ordinal, item_id
        LIMIT %s
        """,
        (*params, limit + 1),
    ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    places = _overlay_catalog_disagreements(
        conn,
        catalog_sha=effective_catalog_sha,
        rows=[dict(row[3]) for row in rows],
    )
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _encode_cursor(scope, [last[0], last[2], last[1]])
    return {
        "stream_id": str(stream_id),
        "unit_id": unit_id,
        "catalog_sha": effective_catalog_sha,
        "publication_id": meta["publication_id"],
        "state_manifest_sha": meta["manifest_sha"],
        "section": "places",
        "phases": list(meta["phases"]),
        "places": places,
        "limit": limit,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def _person_summary(
    row: tuple,
    *,
    manifest_sha: str,
    stream_id: uuid.UUID,
    unit_id: str,
    catalog_sha: str | None,
) -> dict[str, Any]:
    (
        person_id,
        name,
        importance,
        phase_mode,
        certainty,
        reason_codes,
        identity_count,
        change_count,
        preview_identities,
        preview_changes,
    ) = row
    identity_scope = {
        "kind": "unit_person_states",
        "stream_id": str(stream_id),
        "unit_id": unit_id,
        "person_id": person_id,
        "section": "identities",
        "phase_id": None,
        "catalog_sha": catalog_sha,
        "manifest_sha": manifest_sha,
    }
    change_scope = {**identity_scope, "section": "changes"}
    identity_cursor = (
        _encode_cursor(identity_scope, len(preview_identities) - 1)
        if identity_count > len(preview_identities or [])
        else None
    )
    change_cursor = (
        _encode_cursor(change_scope, len(preview_changes) - 1)
        if change_count > len(preview_changes or [])
        else None
    )
    return {
        "person_id": person_id,
        "name": name,
        "importance": importance,
        "phase_mode": phase_mode,
        "certainty": certainty,
        "identities": list(preview_identities or []),
        "identity_count": int(identity_count),
        "has_more_identities": int(identity_count) > len(preview_identities or []),
        "identity_cursor": identity_cursor,
        "changes": list(preview_changes or []),
        "change_count": int(change_count),
        "has_more_changes": int(change_count) > len(preview_changes or []),
        "change_cursor": change_cursor,
        "reason_codes": list(reason_codes or []),
    }


def list_unit_person_states(
    conn,
    *,
    stream_id: uuid.UUID,
    unit_id: str,
    person_id: str,
    section: str,
    phase_id: str | None = None,
    catalog_sha: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return one bounded page of a person's identities or changes for a unit."""
    stream_id = _require_uuid(stream_id, "stream_id")
    unit_id = _require_text(unit_id, "unit_id")
    person_id = _require_text(person_id, "person_id")
    if section not in SECTIONS:
        raise PersistenceError(f"section must be one of {SECTIONS}, got {section!r}")
    if phase_id is not None:
        phase_id = _require_phase_id(phase_id, "phase_id")
    limit = _normalize_limit(limit, maximum=50)
    meta = _manifest_metadata(conn, stream_id=stream_id, unit_id=unit_id)
    if catalog_sha is not None:
        _require_visible_manifest(conn, stream_id=stream_id, catalog_sha=catalog_sha)
    # Membership is validated for every read, catalog present or not.
    _require_unit_person(
        conn, stream_id=stream_id, unit_id=unit_id, person_id=person_id
    )
    if phase_id is not None:
        _require_bound_phase(meta, phase_id)
    # The omitted catalog means the stream's own origin snapshot. Normalize it
    # once so the cursor scope, the response and the overlay all agree.
    effective_catalog_sha = catalog_sha or meta["origin_catalog_sha"]

    scope = {
        "kind": "unit_person_states",
        "stream_id": str(stream_id),
        "unit_id": unit_id,
        "person_id": person_id,
        "section": section,
        "phase_id": phase_id,
        "catalog_sha": effective_catalog_sha,
        "manifest_sha": meta["manifest_sha"],
    }
    item_kind = "identity" if section == "identities" else "change"
    clauses = [
        "stream_id = %s",
        "unit_id = %s",
        "person_id = %s",
        "item_kind = %s",
    ]
    params: list[Any] = [stream_id, unit_id, person_id, item_kind]
    if phase_id is not None:
        if item_kind == "identity":
            clauses.append("%s = ANY (phase_ids)")
        else:
            clauses.append("to_phase_id = %s")
        params.append(phase_id)
    if cursor is not None:
        after_ordinal = _cursor_ordinal(_decode_cursor(cursor, scope))
        clauses.append("item_ordinal > %s")
        params.append(after_ordinal)
    rows = conn.execute(
        f"""
        SELECT item_id, item_ordinal, payload
        FROM chronicle.person_state_items
        WHERE {' AND '.join(clauses)}
        ORDER BY item_ordinal, item_id
        LIMIT %s
        """,
        (*params, limit + 1),
    ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    payloads = [dict(row[2]) for row in rows]
    payloads = _overlay_catalog_disagreements(
        conn, catalog_sha=effective_catalog_sha, rows=payloads
    )
    next_cursor = None
    if has_more and rows:
        next_cursor = _encode_cursor(scope, rows[-1][1])
    items = payloads if section == "identities" else []
    changes = payloads if section == "changes" else []
    return {
        "stream_id": str(stream_id),
        "unit_id": unit_id,
        "catalog_sha": effective_catalog_sha,
        "publication_id": meta["publication_id"],
        "state_manifest_sha": meta["manifest_sha"],
        "person_id": person_id,
        "section": section,
        "phase_id": phase_id,
        "phases": list(meta["phases"]),
        "items": items,
        "changes": changes,
        "item_count": len(payloads),
        "limit": limit,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def list_state_item_evidence(
    conn,
    *,
    stream_id: uuid.UUID,
    unit_id: str,
    person_id: str,
    item_id: str,
    phase_id: str | None = None,
    catalog_sha: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return one bounded page of evidence descriptors for one compiled item."""
    stream_id = _require_uuid(stream_id, "stream_id")
    unit_id = _require_text(unit_id, "unit_id")
    person_id = _require_text(person_id, "person_id")
    item_id = _require_item_id(item_id, "item_id")
    if phase_id is not None:
        phase_id = _require_phase_id(phase_id, "phase_id")
    limit = _normalize_limit(limit, maximum=50)
    meta = _manifest_metadata(conn, stream_id=stream_id, unit_id=unit_id)
    if catalog_sha is not None:
        _require_visible_manifest(conn, stream_id=stream_id, catalog_sha=catalog_sha)
    _require_unit_person(
        conn, stream_id=stream_id, unit_id=unit_id, person_id=person_id
    )
    if phase_id is not None:
        _require_bound_phase(meta, phase_id)
    # The omitted catalog means the stream's own origin snapshot. Normalize it
    # once so the cursor scope and the response agree across pages.
    effective_catalog_sha = catalog_sha or meta["origin_catalog_sha"]

    item = conn.execute(
        "SELECT 1 FROM chronicle.person_state_items"
        " WHERE stream_id = %s AND unit_id = %s AND person_id = %s AND item_id = %s",
        (stream_id, unit_id, person_id, item_id),
    ).fetchone()
    if item is None:
        raise PersistenceError(
            f"unknown item {item_id!r} for person {person_id!r} in stream {stream_id} unit {unit_id}"
        )

    scope = {
        "kind": "state_item_evidence",
        "stream_id": str(stream_id),
        "unit_id": unit_id,
        "person_id": person_id,
        "item_id": item_id,
        "phase_id": phase_id,
        "catalog_sha": effective_catalog_sha,
        "manifest_sha": meta["manifest_sha"],
    }
    clauses = ["stream_id = %s", "unit_id = %s", "item_id = %s"]
    params: list[Any] = [stream_id, unit_id, item_id]
    if phase_id is not None:
        clauses.append("phase_id = %s")
        params.append(phase_id)
    if cursor is not None:
        after_ordinal = _cursor_ordinal(_decode_cursor(cursor, scope))
        clauses.append("descriptor_ordinal > %s")
        params.append(after_ordinal)
    rows = conn.execute(
        f"""
        SELECT descriptor_id, source_publication_id, anchor_id, quote,
               quote_sha256, attribution, source_title, phase_id, relation,
               descriptor_ordinal
        FROM chronicle.person_state_item_evidence
        WHERE {' AND '.join(clauses)}
        ORDER BY descriptor_ordinal
        LIMIT %s
        """,
        (*params, limit + 1),
    ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    descriptors = [
        {
            "descriptor_id": row[0],
            "source_publication_id": str(row[1]),
            "anchor_id": row[2],
            "quote": row[3],
            "quote_sha256": row[4],
            "attribution": row[5],
            "source_title": row[6],
            "phase_id": row[7],
            "relation": row[8],
        }
        for row in rows
    ]
    next_cursor = None
    if has_more and rows:
        next_cursor = _encode_cursor(scope, rows[-1][9])
    return {
        "stream_id": str(stream_id),
        "unit_id": unit_id,
        "catalog_sha": effective_catalog_sha,
        "publication_id": meta["publication_id"],
        "state_manifest_sha": meta["manifest_sha"],
        "item_id": item_id,
        "section": "evidence",
        "phase_id": phase_id,
        "descriptors": descriptors,
        "descriptor_count": len(descriptors),
        "limit": limit,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def _place_evidence_page(
    *, stream_id, unit_id, catalog_sha, meta, item_id, phase_id,
    descriptors, limit, next_cursor, has_more,
) -> dict[str, Any]:
    return {
        "stream_id": str(stream_id),
        "unit_id": unit_id,
        "catalog_sha": catalog_sha,
        "publication_id": str(meta["publication_id"]),
        "state_manifest_sha": meta["manifest_sha"],
        "item_id": item_id,
        "section": "evidence",
        "phase_id": phase_id,
        "descriptors": descriptors,
        "descriptor_count": len(descriptors),
        "limit": limit,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def _require_place_evidence_page_sizes(unit, *, stream_id, catalog_sha) -> None:
    """Reject a descriptor that cannot fit even a one-entry public page."""
    meta = {"publication_id": unit["publication_id"], "manifest_sha": "0" * 64}
    for item in unit["place_items"]:
        descriptors = unit["place_evidence"].get(item["item_id"], [])
        for ordinal, descriptor in enumerate(descriptors):
            phase_id = descriptor["phase_id"]
            scope = {
                "kind": "place_state_item_evidence", "stream_id": str(stream_id),
                "unit_id": unit["unit_id"], "place_id": item["place_id"],
                "item_id": item["item_id"], "phase_id": phase_id,
                "catalog_sha": catalog_sha, "manifest_sha": meta["manifest_sha"],
            }
            page = _place_evidence_page(
                stream_id=stream_id, unit_id=unit["unit_id"], catalog_sha=catalog_sha,
                meta=meta, item_id=item["item_id"], phase_id=phase_id,
                descriptors=[descriptor], limit=50,
                next_cursor=_encode_cursor(scope, ordinal), has_more=True,
            )
            limit = _contract.PersonStateLimits().evidence_max_bytes
            if len(canonical_json_bytes(page)) + STATE_PAGE_CURSOR_MARGIN_BYTES > limit:
                raise PersistenceError(
                    f"place item {item['item_id']!r} descriptor {ordinal} "
                    f"cannot fit evidence_max_bytes {limit}"
                )


def list_place_state_item_evidence(
    conn,
    *,
    stream_id: uuid.UUID,
    unit_id: str,
    place_id: str,
    item_id: str,
    phase_id: str | None = None,
    catalog_sha: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return a bounded evidence page for an administration/control item."""
    stream_id = _require_uuid(stream_id, "stream_id")
    unit_id = _require_text(unit_id, "unit_id")
    place_id = _require_text(place_id, "place_id")
    item_id = _require_item_id(item_id, "item_id")
    if phase_id is not None:
        phase_id = _require_phase_id(phase_id, "phase_id")
    limit = _normalize_limit(limit, maximum=50)
    meta = _manifest_metadata(conn, stream_id=stream_id, unit_id=unit_id)
    if catalog_sha is not None:
        _require_visible_manifest(conn, stream_id=stream_id, catalog_sha=catalog_sha)
    _require_unit_place(
        conn, stream_id=stream_id, unit_id=unit_id, place_id=place_id
    )
    if phase_id is not None:
        _require_bound_phase(meta, phase_id)
    effective_catalog_sha = catalog_sha or meta["origin_catalog_sha"]

    item = conn.execute(
        """
        SELECT 1 FROM chronicle.person_state_place_items
        WHERE stream_id = %s AND unit_id = %s AND place_id = %s AND item_id = %s
        """,
        (stream_id, unit_id, place_id, item_id),
    ).fetchone()
    if item is None:
        raise PersistenceError(
            f"unknown item {item_id!r} for place {place_id!r} in stream "
            f"{stream_id} unit {unit_id}"
        )

    scope = {
        "kind": "place_state_item_evidence",
        "stream_id": str(stream_id),
        "unit_id": unit_id,
        "place_id": place_id,
        "item_id": item_id,
        "phase_id": phase_id,
        "catalog_sha": effective_catalog_sha,
        "manifest_sha": meta["manifest_sha"],
    }
    clauses = [
        "stream_id = %s",
        "unit_id = %s",
        "place_id = %s",
        "item_id = %s",
    ]
    params: list[Any] = [stream_id, unit_id, place_id, item_id]
    if phase_id is not None:
        clauses.append("phase_id = %s")
        params.append(phase_id)
    if cursor is not None:
        after_ordinal = _cursor_ordinal(_decode_cursor(cursor, scope))
        clauses.append("descriptor_ordinal > %s")
        params.append(after_ordinal)
    rows = conn.execute(
        f"""
        SELECT descriptor_id, source_publication_id, anchor_id, quote,
               quote_sha256, attribution, source_title, phase_id, relation,
               descriptor_ordinal
        FROM chronicle.person_state_place_item_evidence
        WHERE {' AND '.join(clauses)}
        ORDER BY descriptor_ordinal
        LIMIT %s
        """,
        (*params, limit + 1),
    ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    descriptors = [
        {
            "descriptor_id": row[0],
            "source_publication_id": str(row[1]),
            "anchor_id": row[2],
            "quote": row[3],
            "quote_sha256": row[4],
            "attribution": row[5],
            "source_title": row[6],
            "phase_id": row[7],
            "relation": row[8],
        }
        for row in rows
    ]
    next_cursor = None
    if has_more and rows:
        next_cursor = _encode_cursor(scope, rows[-1][9])
    return _place_evidence_page(
        stream_id=stream_id, unit_id=unit_id, catalog_sha=effective_catalog_sha,
        meta=meta, item_id=item_id, phase_id=phase_id, descriptors=descriptors,
        limit=limit, next_cursor=next_cursor, has_more=has_more,
    )


def list_catalog_disagreements(
    conn,
    *,
    catalog_sha: str,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return one bounded page of an immutable catalog's disagreement index."""
    catalog_sha = _require_catalog(conn, catalog_sha)
    limit = _normalize_limit(limit, maximum=50)
    scope = {"kind": "catalog_disagreements", "catalog_sha": catalog_sha}
    clauses = ["catalog_sha = %s"]
    params: list[Any] = [catalog_sha]
    if cursor is not None:
        after_id = _cursor_text(_decode_cursor(cursor, scope))
        clauses.append("disagreement_id > %s")
        params.append(after_id)
    rows = conn.execute(
        f"""
        SELECT disagreement_id, topic, fact_refs, phase_ids, reason_codes, sources
        FROM chronicle.person_state_disagreements
        WHERE {' AND '.join(clauses)}
        ORDER BY disagreement_id
        LIMIT %s
        """,
        (*params, limit + 1),
    ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        {
            "disagreement_id": row[0],
            "catalog_sha": catalog_sha,
            "topic": row[1],
            "fact_refs": list(row[2] or []),
            "phase_ids": list(row[3] or []),
            "reason_codes": list(row[4] or []),
            "sources": list(row[5] or []),
        }
        for row in rows
    ]
    next_cursor = None
    if has_more and rows:
        next_cursor = _encode_cursor(scope, rows[-1][0])
    return {
        "catalog_sha": catalog_sha,
        "items": items,
        "item_count": len(items),
        "limit": limit,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


__all__ = [
    "CERTAINTIES",
    "CURSOR_VERSION",
    "EVIDENCE_RELATIONS",
    "IMPORTANCES",
    "ITEM_KINDS",
    "PLACE_DIMENSIONS",
    "OPERATIONS",
    "PHASE_MODES",
    "PersonStateCursorError",
    "QUALIFICATIONS",
    "REASON_CODES",
    "SECTIONS",
    "STATE_DIMENSIONS",
    "list_catalog_disagreements",
    "list_place_state_item_evidence",
    "list_state_item_evidence",
    "list_unit_places",
    "list_unit_people",
    "list_unit_person_states",
    "persist_person_state_assessments",
    "persist_person_state_disagreements",
    "persist_person_state_manifest",
]
