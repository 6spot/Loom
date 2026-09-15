"""Read-only repository for the published person-history product.

The person-history publication is deliberately separate from the global
history edition.  This repository is the boundary that keeps the public read
API on one immutable ``person_histories`` row at a time; candidates, review
records and the current production frontier are never consulted here.

The payload written by T12 contains the accepted summary and prose together
with an evidence index.  Public metadata and paragraph pages project that
payload and expose only evidence handles.  A conclusion read is the explicit
on-demand expansion point for source citations.
"""

from __future__ import annotations

import copy
import re
import uuid
from collections import defaultdict
from typing import Any, Iterable

from read_common import (
    ReadModelError,
    ReadModelNotFound,
    display_surface,
)
from reader_language import simplified
from reading_events import ReadModelInconsistency


READ_VERSION = "0.1"
PUBLICATION_SCHEMA = "chronicle.person-history-publication"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_PERSON_PARAGRAPH_RE = re.compile(r"^pp_[0-9a-f]{24}$")
_PERSON_CONCLUSION_RE = re.compile(r"^[a-z][a-zA-Z0-9_-]{0,63}$")
_MAIN_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,159}$")
_MAPPING_STATUSES = frozenset(("mapped", "ambiguous", "unmapped"))
_CONCLUSION_DIMENSIONS = frozenset(
    ("office", "title", "allegiance", "action", "related_person", "related_place")
)
_STATE_DIMENSIONS = frozenset(("office", "title", "allegiance"))
_QUALIFICATIONS = frozenset(
    ("ordinary", "recommendation", "self_designation", "posthumous", "reported")
)


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _sha(value: Any, description: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise ReadModelError(
            f"{description} must be a lowercase hex SHA-256 string"
        )
    return value


def _uuid(value: Any, description: str) -> tuple[uuid.UUID, str]:
    if not isinstance(value, str) or not value:
        raise ReadModelError(f"{description} must be a UUID")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ReadModelError(f"{description} must be a UUID") from exc
    return parsed, str(parsed)


def _main_reference(value: Any, description: str) -> str:
    if not isinstance(value, str) or not _MAIN_REFERENCE_RE.fullmatch(value):
        raise ReadModelError(
            f"{description} must be a non-empty history reference"
        )
    return value


def _person_paragraph(value: Any) -> str:
    if not isinstance(value, str) or not _PERSON_PARAGRAPH_RE.fullmatch(value):
        raise ReadModelError("invalid person-history paragraph id")
    return value


def _person_conclusion(value: Any) -> str:
    if not isinstance(value, str) or not _PERSON_CONCLUSION_RE.fullmatch(value):
        raise ReadModelError("invalid person-history conclusion id")
    return value


def _published_at(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _name(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("canonical_name") or payload.get("name")
    return simplified(value) if isinstance(value, str) and value else None


def _kind(payload: Any) -> str | None:
    return payload.get("type") if isinstance(payload, dict) else None


def _time_precision(value: Any) -> str:
    """Describe only the precision explicitly present in a phase/date.

    Person-history dates are textual and are intentionally not normalized by
    T12.  A phase with an integer year is therefore ``year``; a phase with
    only a textual period is ``period``; absent values remain ``unknown``.
    """

    if not isinstance(value, dict):
        return "unknown"
    if isinstance(value.get("year"), int) and not isinstance(value.get("year"), bool):
        return "year"
    if isinstance(value.get("period"), str) and value["period"]:
        return "period"
    return "unknown"


def _date_projection(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ReadModelInconsistency("published person-history date is malformed")
    result = {
        "text": value.get("text"),
        "certainty": value.get("certainty"),
        "evidence_ids": [
            item.get("id")
            for item in value.get("evidence", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ],
    }
    if not isinstance(result["text"], str) or not result["text"]:
        raise ReadModelInconsistency("published person-history date has no text")
    if result["certainty"] not in {"clear", "uncertain"}:
        raise ReadModelInconsistency("published person-history date has invalid certainty")
    result["evidence_count"] = len(result["evidence_ids"])
    return result


class PersonHistoryReadRepository:
    """SELECT-only access to one canonical person's published histories."""

    def __init__(self, conn) -> None:
        self.conn = conn

    # ------------------------------------------------------------------
    # Identity and immutable publication loading
    # ------------------------------------------------------------------

    def _person(self, person_id: Any) -> dict[str, Any]:
        parsed, canonical_id = _uuid(person_id, "person id")
        rows = self.conn.execute(
            """
            SELECT r.canonical_id::text, e.payload
            FROM chronicle.canonical_entity_representations r
            JOIN chronicle.staged_entities e
              ON e.bundle_label = r.bundle_label AND e.record_ref = r.record_ref
            WHERE r.canonical_id = %s
            ORDER BY r.bundle_label, r.record_ref
            """,
            (parsed,),
        ).fetchall()
        if not rows:
            raise ReadModelNotFound(f"canonical person {canonical_id} not found")
        kinds = {_kind(row[1]) for row in rows}
        if kinds - {"person"} or "person" not in kinds:
            raise ReadModelNotFound(f"canonical entity {canonical_id} is not a person")
        names = [_name(row[1]) for row in rows]
        name = display_surface(value for value in names if value)
        return {"id": canonical_id, "name": name, "kind": "person"}

    def _publication_row(
        self, *, person_id: str, person_uuid: uuid.UUID, version: str | None
    ) -> tuple[Any, ...] | None:
        params: list[Any] = [person_uuid]
        where = "WHERE person_id = %s"
        if version is not None:
            where += " AND version_sha = %s"
            params.append(version)
        order = "" if version is not None else " ORDER BY publication_sequence DESC"
        row = self.conn.execute(
            """
            SELECT version_sha, person_id::text, catalog_sha, context_sha,
                   source_publication_ids, payload, publication_sequence, published_at
            FROM chronicle.person_histories
            """
            + where
            + order
            + " LIMIT 1",
            tuple(params),
        ).fetchone()
        if row is None and version is not None:
            raise ReadModelNotFound(
                f"person-history version {version} is not published for this person"
            )
        return row

    def _mapping_rows(self, version: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT person_phase_id, mapping_no, mapping_status,
                   main_history_version_sha, main_history_paragraph_id,
                   main_history_phase_id, reason, evidence_conclusion_ids, payload
            FROM chronicle.person_history_mappings
            WHERE person_history_version_sha = %s
            ORDER BY person_phase_id, mapping_no
            """,
            (version,),
        ).fetchall()
        result = []
        for row in rows:
            status = row[2]
            if status not in _MAPPING_STATUSES:
                raise ReadModelInconsistency(
                    "published person-history mapping has invalid status"
                )
            phase_id = row[0]
            if not isinstance(phase_id, str) or not _PERSON_CONCLUSION_RE.fullmatch(phase_id):
                raise ReadModelInconsistency(
                    "published person-history mapping has an invalid phase"
                )
            mapping_no = row[1]
            if type(mapping_no) is not int or mapping_no < 0:
                raise ReadModelInconsistency(
                    "published person-history mapping has an invalid number"
                )
            reason = row[6]
            if not isinstance(reason, str) or not reason:
                raise ReadModelInconsistency("published person-history mapping has no reason")
            main_version = row[3]
            main_paragraph = row[4]
            if status == "unmapped":
                if main_version is not None or main_paragraph is not None:
                    raise ReadModelInconsistency(
                        "unmapped person-history mapping carries a main-history target"
                    )
            elif (
                not isinstance(main_version, str)
                or not _SHA_RE.fullmatch(main_version)
                or not isinstance(main_paragraph, str)
                or not _MAIN_REFERENCE_RE.fullmatch(main_paragraph)
            ):
                raise ReadModelInconsistency(
                    "mapped person-history mapping has no main-history target"
                )
            main_phase = row[5]
            if main_phase is not None and (
                not isinstance(main_phase, str) or not _MAIN_REFERENCE_RE.fullmatch(main_phase)
            ):
                raise ReadModelInconsistency(
                    "person-history mapping has an invalid main-history phase"
                )
            evidence_ids = list(row[7] or [])
            if any(
                not isinstance(value, str) or not _PERSON_CONCLUSION_RE.fullmatch(value)
                for value in evidence_ids
            ):
                raise ReadModelInconsistency(
                    "person-history mapping has invalid evidence conclusion ids"
                )
            result.append(
                {
                    "person_phase_id": phase_id,
                    "mapping_no": mapping_no,
                    "mapping_status": status,
                    "main_history_version_sha": main_version,
                    "main_history_paragraph_id": main_paragraph,
                    "main_history_phase_id": main_phase,
                    "reason": reason,
                    "evidence_conclusion_ids": evidence_ids,
                    "payload": _copy(row[8]) if isinstance(row[8], dict) else {},
                }
            )
        return result

    def _load(
        self, *, person: dict[str, Any], person_uuid: uuid.UUID, version: str | None
    ) -> dict[str, Any] | None:
        row = self._publication_row(
            person_id=person["id"], person_uuid=person_uuid, version=version
        )
        if row is None:
            return None
        (
            row_version,
            row_person_id,
            catalog_sha,
            context_sha,
            source_publication_ids,
            payload,
            publication_sequence,
            published_at,
        ) = row
        if not isinstance(payload, dict):
            raise ReadModelInconsistency("published person-history payload is not an object")
        if payload.get("schema") != PUBLICATION_SCHEMA or payload.get("version") != READ_VERSION:
            raise ReadModelInconsistency("published person-history payload has an invalid schema")
        row_version = str(row_version)
        if payload.get("publication_version") != row_version:
            raise ReadModelInconsistency(
                "published person-history payload version does not match its row"
            )
        if (
            payload.get("catalog_sha") != str(catalog_sha)
            or payload.get("context_sha256") != str(context_sha)
        ):
            raise ReadModelInconsistency(
                "published person-history payload scope does not match its row"
            )
        if str(row_person_id) != person["id"] or payload.get("person_id") != person["id"]:
            raise ReadModelInconsistency(
                "published person-history payload changes the canonical person"
            )
        payload_person = payload.get("person")
        if (
            not isinstance(payload_person, dict)
            or payload_person.get("id") != person["id"]
            or payload_person.get("kind") != "person"
        ):
            raise ReadModelInconsistency(
                "published person-history payload has an invalid person identity"
            )
        paragraphs = payload.get("paragraphs")
        phases = payload.get("phases")
        conclusions = payload.get("conclusions")
        coverage = payload.get("coverage")
        if (
            not isinstance(paragraphs, list)
            or not paragraphs
            or not isinstance(phases, list)
            or not phases
            or not isinstance(conclusions, list)
            or not conclusions
            or not isinstance(coverage, dict)
        ):
            raise ReadModelInconsistency(
                "published person-history payload is missing its complete products"
            )
        evidence_index = payload.get("evidence")
        if not isinstance(evidence_index, dict) or not evidence_index:
            raise ReadModelInconsistency("published person-history payload has no evidence index")
        for evidence_id, evidence in evidence_index.items():
            if (
                not isinstance(evidence_id, str)
                or not _PERSON_CONCLUSION_RE.fullmatch(evidence_id)
                or not isinstance(evidence, dict)
                or not isinstance(evidence.get("publication_id"), str)
                or not evidence["publication_id"]
                or not isinstance(evidence.get("anchor_id"), str)
                or not evidence["anchor_id"]
            ):
                raise ReadModelInconsistency("published person-history evidence index is malformed")
        db_publications = [str(value) for value in (source_publication_ids or [])]
        payload_publications = payload.get("source_publication_ids")
        if (
            not isinstance(source_publication_ids, list)
            or not db_publications
            or any(not value for value in db_publications)
            or payload_publications != db_publications
        ):
            raise ReadModelInconsistency(
                "published person-history source publication binding changed"
            )
        mapping_rows = self._mapping_rows(row_version)
        if any(not isinstance(item, dict) for item in phases):
            raise ReadModelInconsistency("published person-history phases are malformed")
        phase_ids = [item.get("id") for item in phases]
        if (
            any(
                not isinstance(value, str) or not _PERSON_CONCLUSION_RE.fullmatch(value)
                for value in phase_ids
            )
            or len(set(phase_ids)) != len(phase_ids)
        ):
            raise ReadModelInconsistency("published person-history phases are malformed")
        by_phase = defaultdict(list)
        for item in mapping_rows:
            phase_id = item["person_phase_id"]
            if phase_id not in phase_ids:
                raise ReadModelInconsistency(
                    "published person-history mapping references an unknown phase"
                )
            by_phase[phase_id].append(item)
        if set(by_phase) != set(phase_ids):
            raise ReadModelInconsistency(
                "published person-history mapping does not cover every phase"
            )
        phase_by_id = {item["id"]: item for item in phases}
        for phase_id, items in by_phase.items():
            declared = phase_by_id[phase_id].get("mapping_status")
            statuses = {item["mapping_status"] for item in items}
            if len(statuses) != 1 or declared not in statuses:
                raise ReadModelInconsistency(
                    "published person-history phase and mapping status disagree"
                )
            if declared == "unmapped" and len(items) != 1:
                raise ReadModelInconsistency(
                    "unmapped person-history phase has multiple mapping rows"
                )
            position_ids = phase_by_id[phase_id].get("mapping_position_ids")
            if not isinstance(position_ids, list):
                raise ReadModelInconsistency(
                    "published person-history phase has no mapping positions"
                )
            if any(
                not isinstance(value, str) or not _PERSON_CONCLUSION_RE.fullmatch(value)
                for value in position_ids
            ) or len(set(position_ids)) != len(position_ids):
                raise ReadModelInconsistency(
                    "published person-history phase has invalid mapping positions"
                )
            if declared == "unmapped" and position_ids:
                raise ReadModelInconsistency(
                    "unmapped person-history phase has mapping positions"
                )
            if declared != "unmapped" and len(position_ids) != len(items):
                raise ReadModelInconsistency(
                    "published person-history mapping row count disagrees with the phase"
                )
            if [item["mapping_no"] for item in items] != list(range(len(items))):
                raise ReadModelInconsistency(
                    "published person-history mapping numbers are not contiguous"
                )
        paragraph_ids: list[str] = []
        paragraph_phases: list[str] = []
        for ordinal, paragraph in enumerate(paragraphs):
            if not isinstance(paragraph, dict):
                raise ReadModelInconsistency("published person-history paragraphs are malformed")
            paragraph_id = paragraph.get("id")
            phase_id = paragraph.get("phase_id")
            if (
                not isinstance(paragraph_id, str)
                or not _PERSON_PARAGRAPH_RE.fullmatch(paragraph_id)
                or paragraph_id in paragraph_ids
                or not isinstance(phase_id, str)
                or phase_id not in phase_ids
            ):
                raise ReadModelInconsistency(
                    "published person-history paragraph identity is malformed"
                )
            declared_ordinal = paragraph.get("ordinal")
            if type(declared_ordinal) is not int or declared_ordinal != ordinal:
                raise ReadModelInconsistency(
                    "published person-history paragraph order is malformed"
                )
            segment_list = paragraph.get("segments")
            if not isinstance(segment_list, list) or not segment_list:
                raise ReadModelInconsistency("published person-history paragraph has no segments")
            paragraph_ids.append(paragraph_id)
            paragraph_phases.append(phase_id)
            segment_conclusion_ids: list[str] = []
            for segment in segment_list:
                if (
                    not isinstance(segment, dict)
                    or not isinstance(segment.get("text"), str)
                    or not segment["text"]
                ):
                    raise ReadModelInconsistency("published person-history segment is malformed")
                segment_ids = segment.get("conclusion_ids")
                if not isinstance(segment_ids, list) or not segment_ids:
                    raise ReadModelInconsistency(
                        "published person-history segment has no conclusions"
                    )
                for conclusion_id in segment_ids:
                    if not isinstance(conclusion_id, str) or not _PERSON_CONCLUSION_RE.fullmatch(
                        conclusion_id
                    ):
                        raise ReadModelInconsistency(
                            "published person-history segment has an invalid conclusion"
                        )
                    segment_conclusion_ids.append(conclusion_id)
            declared_conclusion_ids = paragraph.get("conclusion_ids")
            if (
                not isinstance(declared_conclusion_ids, list)
                or set(declared_conclusion_ids) != set(segment_conclusion_ids)
            ):
                raise ReadModelInconsistency(
                    "published person-history paragraph conclusion binding is malformed"
                )
        if set(paragraph_phases) != set(phase_ids):
            raise ReadModelInconsistency(
                "published person-history paragraphs do not cover every phase"
            )
        conclusion_ids: list[str] = []
        for conclusion in conclusions:
            if not isinstance(conclusion, dict):
                raise ReadModelInconsistency("published person-history conclusions are malformed")
            conclusion_id = conclusion.get("id")
            phase_membership = conclusion.get("phase_ids")
            related_entity_ids = conclusion.get("related_entity_ids")
            event_id = conclusion.get("event_id")
            evidence_refs = conclusion.get("evidence")
            if (
                not isinstance(conclusion_id, str)
                or not _PERSON_CONCLUSION_RE.fullmatch(conclusion_id)
                or conclusion_id in conclusion_ids
                or conclusion.get("person_id") != person["id"]
                or not isinstance(phase_membership, list)
                or not phase_membership
                or any(
                    not isinstance(value, str) or value not in phase_ids
                    for value in phase_membership
                )
                or len(set(phase_membership)) != len(phase_membership)
                or conclusion.get("dimension") not in _CONCLUSION_DIMENSIONS
                or conclusion.get("certainty") not in {"clear", "uncertain"}
                or conclusion.get("qualification") not in _QUALIFICATIONS
                or (
                    conclusion.get("value") is not None
                    and not isinstance(conclusion.get("value"), str)
                )
                or (
                    event_id is not None
                    and (not isinstance(event_id, str) or not event_id)
                )
                or not isinstance(related_entity_ids, list)
                or any(not isinstance(value, str) or not value for value in related_entity_ids)
                or len(set(related_entity_ids)) != len(related_entity_ids)
                or not isinstance(evidence_refs, list)
                or not evidence_refs
                or any(
                    not isinstance(ref, dict)
                    or not isinstance(ref.get("id"), str)
                    or not _PERSON_CONCLUSION_RE.fullmatch(ref["id"])
                    for ref in evidence_refs
                )
            ):
                raise ReadModelInconsistency(
                    "published person-history conclusion identity is malformed"
                )
            evidence_ids = [ref["id"] for ref in evidence_refs]
            if len(set(evidence_ids)) != len(evidence_ids):
                raise ReadModelInconsistency("published person-history conclusions repeat evidence")
            conclusion_ids.append(conclusion_id)
        if not conclusion_ids:
            raise ReadModelInconsistency("published person-history has no conclusions")
        phase_basis_ids = [
            value
            for phase in phases
            for value in (phase.get("basis") or [])
        ]
        if (
            any(
                not isinstance(value, str) or value not in evidence_index
                for value in phase_basis_ids
            )
            or len(phase_basis_ids) == 0
        ):
            raise ReadModelInconsistency(
                "published person-history phase evidence binding is malformed"
            )
        conclusion_evidence_ids = [
            ref["id"]
            for conclusion in conclusions
            for ref in conclusion["evidence"]
        ]
        if any(value not in evidence_index for value in conclusion_evidence_ids):
            raise ReadModelInconsistency(
                "published person-history conclusion evidence binding is malformed"
            )
        conclusion_id_set = set(conclusion_ids)
        for item in mapping_rows:
            if any(value not in conclusion_id_set for value in item["evidence_conclusion_ids"]):
                raise ReadModelInconsistency(
                    "published person-history mapping references an unknown conclusion"
                )
        return {
            "version": row_version,
            "person_id": person["id"],
            "person": {
                "id": person["id"],
                "name": payload_person.get("name") or person.get("name"),
                "kind": "person",
            },
            "catalog_sha": str(catalog_sha),
            "context_sha256": str(context_sha),
            "source_publication_ids": db_publications,
            "coverage": _copy(coverage),
            "overview": payload.get("overview"),
            "birth": _copy(payload.get("birth")),
            "death": _copy(payload.get("death")),
            "phases": _copy(phases),
            "paragraphs": _copy(paragraphs),
            "conclusions": _copy(conclusions),
            "evidence": _copy(evidence_index),
            "mapping_rows": mapping_rows,
            "phase_by_id": phase_by_id,
            "published_at": _published_at(published_at),
            "publication_sequence": int(publication_sequence),
        }

    def _snapshot(
        self, person_id: Any, version: str | None = None, *, required: bool = True
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        person_uuid, canonical_id = _uuid(person_id, "person id")
        person = self._person(canonical_id)
        snapshot = self._load(person=person, person_uuid=person_uuid, version=version)
        if snapshot is None and required:
            raise ReadModelNotFound("this person has no published history version")
        return person, snapshot

    # ------------------------------------------------------------------
    # Related canonical objects
    # ------------------------------------------------------------------

    def _related_objects(self, ids: Iterable[Any]) -> dict[str, dict[str, Any]]:
        canonical_ids = sorted({str(value) for value in ids if isinstance(value, str) and value})
        valid: list[tuple[str, uuid.UUID]] = []
        for value in canonical_ids:
            try:
                valid.append((value, uuid.UUID(value)))
            except (ValueError, AttributeError, TypeError):
                # Published T12 data normally contains UUIDs.  Keep an
                # invalid persisted handle visible as an unexpanded ID rather
                # than inventing a name or silently matching by text.
                continue
        result = {
            value: {
                "id": value,
                "canonical_id": value,
                "kind": None,
                "name": None,
            }
            for value in canonical_ids
        }
        if not valid:
            return result
        placeholders = ", ".join("%s::uuid" for _ in valid)
        rows = self.conn.execute(
            """
            SELECT r.canonical_id::text, e.payload
            FROM chronicle.canonical_entity_representations r
            JOIN chronicle.staged_entities e
              ON e.bundle_label = r.bundle_label AND e.record_ref = r.record_ref
            WHERE r.canonical_id IN ("""
            + placeholders
            + ") ORDER BY r.canonical_id, r.bundle_label, r.record_ref",
            tuple(value for _text, value in valid),
        ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for canonical_id, payload in rows:
            if isinstance(payload, dict):
                grouped[str(canonical_id)].append(payload)
        for canonical_id, payloads in grouped.items():
            names = [_name(payload) for payload in payloads]
            result[canonical_id] = {
                "id": canonical_id,
                "canonical_id": canonical_id,
                "kind": display_surface(_kind(payload) for payload in payloads),
                "name": display_surface(value for value in names if value),
            }
        return result

    def _related_events(self, ids: Iterable[Any]) -> dict[str, dict[str, Any]]:
        canonical_ids = sorted({str(value) for value in ids if isinstance(value, str) and value})
        valid: list[tuple[str, uuid.UUID]] = []
        for value in canonical_ids:
            try:
                valid.append((value, uuid.UUID(value)))
            except (ValueError, AttributeError, TypeError):
                continue
        result = {
            value: {
                "id": value,
                "canonical_id": value,
                "kind": "event",
                "name": None,
            }
            for value in canonical_ids
        }
        if not valid:
            return result
        placeholders = ", ".join("%s::uuid" for _ in valid)
        rows = self.conn.execute(
            """
            SELECT r.canonical_id::text, e.payload
            FROM chronicle.canonical_event_representations r
            JOIN chronicle.staged_events e
              ON e.bundle_label = r.bundle_label AND e.record_ref = r.record_ref
            WHERE r.canonical_id IN ("""
            + placeholders
            + ") ORDER BY r.canonical_id, r.bundle_label, r.record_ref",
            tuple(value for _text, value in valid),
        ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for canonical_id, payload in rows:
            if isinstance(payload, dict):
                grouped[str(canonical_id)].append(payload)
        for canonical_id, payloads in grouped.items():
            names = [
                payload.get("title") or payload.get("name")
                for payload in payloads
                if isinstance(payload, dict)
            ]
            result[canonical_id] = {
                "id": canonical_id,
                "canonical_id": canonical_id,
                "kind": "event",
                "name": display_surface(
                    simplified(value) for value in names if isinstance(value, str) and value
                ),
            }
        return result

    def _source_titles(self, publication_ids: Iterable[Any]) -> dict[str, str | None]:
        """Resolve source titles without widening evidence ownership.

        The evidence index already binds each citation to a publication and
        anchor.  This lookup adds a display title only; it never searches by
        quote or substitutes a different publication.
        """

        values = sorted(
            {
                str(value)
                for value in publication_ids
                if isinstance(value, str) and value
            }
        )
        valid: list[tuple[str, uuid.UUID]] = []
        for value in values:
            try:
                valid.append((value, uuid.UUID(value)))
            except (ValueError, AttributeError, TypeError):
                continue
        result = {value: None for value in values}
        if not valid:
            return result
        placeholders = ", ".join("%s::uuid" for _ in valid)
        rows = self.conn.execute(
            """
            SELECT p.publication_id::text, d.title
            FROM chronicle.chapter_publications p
            JOIN chronicle.documents d ON d.document_id = p.document_id
            WHERE p.publication_id IN ("""
            + placeholders
            + ") ORDER BY p.publication_id",
            tuple(value for _text, value in valid),
        ).fetchall()
        for publication_id, title in rows:
            if isinstance(title, str) and title:
                result[str(publication_id)] = simplified(title)
        return result

    # ------------------------------------------------------------------
    # Projection helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mapping_target(item: dict[str, Any]) -> dict[str, Any] | None:
        if item["mapping_status"] == "unmapped":
            return None
        result = {
            "person_phase_id": item["person_phase_id"],
            "mapping_no": item["mapping_no"],
            "status": item["mapping_status"],
            "mapping_status": item["mapping_status"],
            "version": item["main_history_version_sha"],
            "paragraph_id": item["main_history_paragraph_id"],
            "phase_id": item["main_history_phase_id"],
            "main_history_version_sha": item["main_history_version_sha"],
            "main_history_paragraph_id": item["main_history_paragraph_id"],
            "main_history_phase_id": item["main_history_phase_id"],
        }
        position_id = item["payload"].get("position_id")
        if isinstance(position_id, str) and _PERSON_CONCLUSION_RE.fullmatch(position_id):
            result["position_id"] = position_id
        return result

    def _phase_projection(
        self, snapshot: dict[str, Any], phase: dict[str, Any]
    ) -> dict[str, Any]:
        phase_id = phase.get("id")
        rows = [
            item
            for item in snapshot["mapping_rows"]
            if item["person_phase_id"] == phase_id
        ]
        if not rows:
            raise ReadModelInconsistency("published person-history phase has no mapping")
        targets = [
            target
            for item in rows
            if (target := self._mapping_target(item)) is not None
        ]
        status = rows[0]["mapping_status"]
        reason = rows[0]["reason"]
        result = {
            "id": phase_id,
            "phase_id": phase_id,
            "label": phase.get("label"),
            "year": phase.get("year"),
            "period": phase.get("period"),
            "time_precision": _time_precision(phase),
            "relation_to_previous": phase.get("relation_to_previous"),
            "mapping_status": status,
            "mapping_reason": reason,
            "mapping_position_ids": list(phase.get("mapping_position_ids") or []),
            "mapping": {
                "status": status,
                "reason": reason,
                "targets": targets,
            },
            "mapping_targets": targets,
        }
        return result

    def _conclusion_projection(
        self,
        conclusion: dict[str, Any],
        *,
        entity_objects: dict[str, dict[str, Any]],
        event_objects: dict[str, dict[str, Any]],
        include_evidence: bool = False,
        evidence_index: dict[str, Any] | None = None,
        source_titles: dict[str, str | None] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(conclusion, dict):
            raise ReadModelInconsistency("published person-history conclusion is malformed")
        conclusion_id = conclusion.get("id")
        if not isinstance(conclusion_id, str) or not _PERSON_CONCLUSION_RE.fullmatch(conclusion_id):
            raise ReadModelInconsistency("published person-history conclusion has an invalid id")
        dimension = conclusion.get("dimension")
        if dimension not in _CONCLUSION_DIMENSIONS:
            raise ReadModelInconsistency(
                "published person-history conclusion has an invalid dimension"
            )
        phase_ids = conclusion.get("phase_ids")
        if (
            not isinstance(phase_ids, list)
            or not phase_ids
            or any(
                not isinstance(value, str) or not _PERSON_CONCLUSION_RE.fullmatch(value)
                for value in phase_ids
            )
            or len(set(phase_ids)) != len(phase_ids)
        ):
            raise ReadModelInconsistency("published person-history conclusion has invalid phases")
        related_entity_values = conclusion.get("related_entity_ids")
        if (
            not isinstance(related_entity_values, list)
            or any(not isinstance(value, str) or not value for value in related_entity_values)
            or len(set(related_entity_values)) != len(related_entity_values)
        ):
            raise ReadModelInconsistency(
                "published person-history conclusion has invalid related entities"
            )
        event_id = conclusion.get("event_id")
        if event_id is not None and (not isinstance(event_id, str) or not event_id):
            raise ReadModelInconsistency("published person-history conclusion has an invalid event")
        evidence_refs = conclusion.get("evidence")
        if (
            not isinstance(evidence_refs, list)
            or not evidence_refs
            or any(
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or not _PERSON_CONCLUSION_RE.fullmatch(item["id"])
                for item in evidence_refs
            )
        ):
            raise ReadModelInconsistency("published person-history conclusion has no evidence refs")
        evidence_ids = [item["id"] for item in evidence_refs]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ReadModelInconsistency("published person-history conclusion repeats evidence")
        related_ids = list(related_entity_values)
        related_objects = [
            entity_objects[value] for value in related_ids if value in entity_objects
        ]
        if isinstance(event_id, str) and event_id in event_objects:
            related_objects.append(event_objects[event_id])
        result = {
            "id": conclusion_id,
            "person_id": conclusion.get("person_id"),
            "dimension": dimension,
            "phase_ids": list(phase_ids),
            "text": conclusion.get("text"),
            "value": conclusion.get("value"),
            "certainty": conclusion.get("certainty"),
            "qualification": conclusion.get("qualification"),
            "event_id": event_id,
            "related_entity_ids": related_ids,
            "related_objects": related_objects,
            "evidence_ids": evidence_ids,
            "evidence_count": len(evidence_ids),
        }
        if include_evidence:
            if not isinstance(evidence_index, dict):
                raise ReadModelInconsistency("person-history evidence index is missing")
            result["evidence"] = [
                self._evidence_projection(
                    ref,
                    evidence_index=evidence_index,
                    source_titles=source_titles,
                )
                for ref in evidence_refs
            ]
        return result

    @staticmethod
    def _evidence_projection(
        ref: Any,
        *,
        evidence_index: dict[str, Any],
        source_titles: dict[str, str | None] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(ref, dict) or not isinstance(ref.get("id"), str):
            raise ReadModelInconsistency("published person-history evidence ref is malformed")
        evidence_id = ref["id"]
        stored = evidence_index.get(evidence_id)
        if not isinstance(stored, dict):
            raise ReadModelInconsistency(
                f"published person-history evidence {evidence_id} is missing"
            )
        publication_id = stored.get("publication_id")
        anchor_id = stored.get("anchor_id")
        if (
            not isinstance(publication_id, str)
            or not publication_id
            or not isinstance(anchor_id, str)
            or not anchor_id
        ):
            raise ReadModelInconsistency(
                f"published person-history evidence {evidence_id} has no source locator"
            )
        result = {
            "id": evidence_id,
            "evidence_id": evidence_id,
            "relation": ref.get("relation"),
            "attribution": ref.get("attribution"),
            "note": ref.get("note"),
            "source_id": stored.get("source_id"),
            "publication_id": publication_id,
            "source_title": (source_titles or {}).get(publication_id),
            "anchor_id": anchor_id,
            "quote": stored.get("quote"),
            "start": stored.get("start"),
            "end": stored.get("end"),
            "source": {
                "publication_id": publication_id,
                "anchor_id": anchor_id,
                "path": f"/api/v1/public/chapters/{publication_id}/sources/{anchor_id}",
            },
        }
        return result

    def _paragraph_projection(
        self,
        snapshot: dict[str, Any],
        paragraph: dict[str, Any],
        *,
        entity_objects: dict[str, dict[str, Any]],
        event_objects: dict[str, dict[str, Any]],
        conclusion_by_id: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(paragraph, dict):
            raise ReadModelInconsistency("published person-history paragraph is malformed")
        paragraph_id = paragraph.get("id")
        phase_id = paragraph.get("phase_id")
        ordinal = paragraph.get("ordinal")
        if (
            not isinstance(paragraph_id, str)
            or not _PERSON_PARAGRAPH_RE.fullmatch(paragraph_id)
            or not isinstance(phase_id, str)
            or type(ordinal) is not int
            or ordinal < 0
        ):
            raise ReadModelInconsistency("published person-history paragraph has no identity")
        phase = snapshot["phase_by_id"].get(phase_id)
        if phase is None:
            raise ReadModelInconsistency(
                "published person-history paragraph references an unknown phase"
            )
        segments = paragraph.get("segments")
        if not isinstance(segments, list) or not segments:
            raise ReadModelInconsistency("published person-history paragraph has no segments")
        projected_segments = []
        for segment in segments:
            if not isinstance(segment, dict):
                raise ReadModelInconsistency("published person-history segment is malformed")
            text = segment.get("text")
            raw_conclusion_ids = segment.get("conclusion_ids")
            raw_related_ids = segment.get("related_entity_ids")
            event_id = segment.get("event_id")
            if (
                not isinstance(text, str)
                or not text
                or not isinstance(raw_conclusion_ids, list)
                or not raw_conclusion_ids
                or any(
                    not isinstance(value, str)
                    or not _PERSON_CONCLUSION_RE.fullmatch(value)
                    for value in raw_conclusion_ids
                )
                or len(set(raw_conclusion_ids)) != len(raw_conclusion_ids)
                or not isinstance(raw_related_ids, list)
                or any(not isinstance(value, str) or not value for value in raw_related_ids)
                or len(set(raw_related_ids)) != len(raw_related_ids)
                or (event_id is not None and (not isinstance(event_id, str) or not event_id))
            ):
                raise ReadModelInconsistency("published person-history segment is malformed")
            conclusion_ids = list(raw_conclusion_ids)
            conclusions = []
            for conclusion_id in conclusion_ids:
                conclusion = conclusion_by_id.get(conclusion_id)
                if conclusion is None:
                    raise ReadModelInconsistency(
                        "published person-history paragraph references unknown conclusion "
                        f"{conclusion_id}"
                    )
                conclusions.append(
                    self._conclusion_projection(
                        conclusion,
                        entity_objects=entity_objects,
                        event_objects=event_objects,
                    )
                )
            related_ids = list(raw_related_ids)
            related_objects = [
                entity_objects[value]
                for value in related_ids
                if value in entity_objects
            ]
            if isinstance(event_id, str) and event_id in event_objects:
                related_objects.append(event_objects[event_id])
            for item in conclusions:
                for related in item["related_objects"]:
                    if not any(existing["id"] == related["id"] for existing in related_objects):
                        related_objects.append(related)
            states = [
                item for item in conclusions
                if item["dimension"] in _STATE_DIMENSIONS
            ]
            actions = [
                item for item in conclusions
                if item["dimension"] == "action"
            ]
            projected_segments.append(
                {
                    "text": text,
                    "conclusion_ids": conclusion_ids,
                    "event_id": event_id,
                    "related_entity_ids": related_ids,
                    "related_objects": related_objects,
                    "states": states,
                    "actions": actions,
                }
            )
        paragraph_related_objects: list[dict[str, Any]] = []
        paragraph_states: list[dict[str, Any]] = []
        paragraph_actions: list[dict[str, Any]] = []
        paragraph_related_ids: list[str] = []
        paragraph_conclusion_ids: list[str] = []
        for segment in projected_segments:
            for value in segment["related_entity_ids"]:
                if value not in paragraph_related_ids:
                    paragraph_related_ids.append(value)
            for item in segment["related_objects"]:
                if not any(existing["id"] == item["id"] for existing in paragraph_related_objects):
                    paragraph_related_objects.append(item)
            for item in segment["states"]:
                if item["id"] not in {value["id"] for value in paragraph_states}:
                    paragraph_states.append(item)
            for item in segment["actions"]:
                if item["id"] not in {value["id"] for value in paragraph_actions}:
                    paragraph_actions.append(item)
            for value in segment["conclusion_ids"]:
                if value not in paragraph_conclusion_ids:
                    paragraph_conclusion_ids.append(value)
        return {
            "id": paragraph_id,
            "paragraph_id": paragraph_id,
            "ordinal": ordinal,
            "phase_id": phase_id,
            "phase": self._phase_projection(snapshot, phase),
            "segments": projected_segments,
            "text": "".join(
                segment["text"]
                for segment in projected_segments
                if isinstance(segment["text"], str)
            ),
            "conclusion_ids": paragraph_conclusion_ids,
            "states": paragraph_states,
            "actions": paragraph_actions,
            "related_entity_ids": paragraph_related_ids,
            "related_objects": paragraph_related_objects,
        }

    def _project_paragraphs(
        self, snapshot: dict[str, Any], paragraphs: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        conclusions = snapshot["conclusions"]
        conclusion_by_id = {}
        entity_ids: set[str] = set()
        event_ids: set[str] = set()
        for conclusion in conclusions:
            if not isinstance(conclusion, dict) or not isinstance(conclusion.get("id"), str):
                raise ReadModelInconsistency("published person-history conclusions are malformed")
            if conclusion["id"] in conclusion_by_id:
                raise ReadModelInconsistency("published person-history conclusions repeat an id")
            if conclusion.get("person_id") != snapshot["person_id"]:
                raise ReadModelInconsistency(
                    "published person-history conclusion changes the canonical person"
                )
            conclusion_by_id[conclusion["id"]] = conclusion
            entity_ids.update(
                value
                for value in conclusion.get("related_entity_ids", [])
                if isinstance(value, str)
            )
            if isinstance(conclusion.get("event_id"), str):
                event_ids.add(conclusion["event_id"])
        for paragraph in paragraphs:
            if isinstance(paragraph, dict):
                for segment in paragraph.get("segments", []):
                    if not isinstance(segment, dict):
                        continue
                    entity_ids.update(
                        value
                        for value in segment.get("related_entity_ids", [])
                        if isinstance(value, str)
                    )
                    if isinstance(segment.get("event_id"), str):
                        event_ids.add(segment["event_id"])
        entity_objects = self._related_objects(entity_ids)
        event_objects = self._related_events(event_ids)
        return [
            self._paragraph_projection(
                snapshot,
                paragraph,
                entity_objects=entity_objects,
                event_objects=event_objects,
                conclusion_by_id=conclusion_by_id,
            )
            for paragraph in paragraphs
        ]

    # ------------------------------------------------------------------
    # Main-history mapping
    # ------------------------------------------------------------------

    def _resolve_main_locator(self, *, version: str, paragraph_id: str) -> dict[str, str]:
        """Resolve a public T10 paragraph to the T12 mapping-table key.

        T12 stores the source narrative fragment version and local paragraph
        ID because that is the exact handle available during production.  A
        T10 edition exposes a global ``hp_`` ID, so this read-only bridge uses
        the immutable edition index to recover the stored fragment/local pair.
        It never falls back to a name, year or phase comparison.
        """

        edition_row = self.conn.execute(
            """
            SELECT fragment_version, source_paragraph_id, phase_id
            FROM chronicle.history_edition_paragraph_index
            WHERE edition_version = %s AND paragraph_id = %s
            """,
            (version, paragraph_id),
        ).fetchone()
        if edition_row is not None:
            return {
                "requested_version": version,
                "requested_paragraph_id": paragraph_id,
                "source_version": str(edition_row[0]),
                "source_paragraph_id": str(edition_row[1]),
                "source_phase_id": str(edition_row[2]),
            }
        edition_exists = self.conn.execute(
            "SELECT 1 FROM chronicle.history_editions WHERE edition_version = %s",
            (version,),
        ).fetchone()
        if edition_exists is not None:
            raise ReadModelNotFound("main-history paragraph is outside this fixed edition")
        row = self.conn.execute(
            "SELECT payload FROM chronicle.historical_narratives WHERE version_sha = %s",
            (version,),
        ).fetchone()
        if row is None or not isinstance(row[0], dict):
            raise ReadModelNotFound("main-history version is not published")
        paragraphs = row[0].get("paragraphs")
        if not isinstance(paragraphs, list):
            raise ReadModelInconsistency("published main-history payload has no paragraphs")
        for paragraph in paragraphs:
            if not isinstance(paragraph, dict):
                continue
            source_id = paragraph.get("id", paragraph.get("paragraph_id"))
            if source_id == paragraph_id:
                phase_id = paragraph.get("phase_id")
                if not isinstance(phase_id, str):
                    raise ReadModelInconsistency(
                        "published main-history paragraph has no phase"
                    )
                return {
                    "requested_version": version,
                    "requested_paragraph_id": paragraph_id,
                    "source_version": version,
                    "source_paragraph_id": paragraph_id,
                    "source_phase_id": phase_id,
                }
        raise ReadModelNotFound("main-history paragraph is outside this published version")

    def _mapping_for_locator(
        self,
        snapshot: dict[str, Any],
        *,
        main_version: str,
        paragraph_id: str,
        phase_id: str | None = None,
    ) -> dict[str, Any]:
        main_version = _sha(main_version, "main-history version")
        paragraph_id = _main_reference(paragraph_id, "main-history paragraph id")
        if phase_id is not None:
            phase_id = _main_reference(phase_id, "main-history phase id")
        locator = self._resolve_main_locator(version=main_version, paragraph_id=paragraph_id)
        if phase_id is not None and phase_id != locator["source_phase_id"]:
            raise ReadModelNotFound("main-history phase is outside this paragraph")
        exact = [
            item
            for item in snapshot["mapping_rows"]
            if item["mapping_status"] != "unmapped"
            and item["main_history_version_sha"] == locator["source_version"]
            and item["main_history_paragraph_id"] == locator["source_paragraph_id"]
        ]
        matched_phases = sorted({item["person_phase_id"] for item in exact})
        groups = []
        for person_phase_id in matched_phases:
            rows = [
                item
                for item in snapshot["mapping_rows"]
                if item["person_phase_id"] == person_phase_id
            ]
            groups.append(
                {
                    "phase_id": person_phase_id,
                    "person_phase_id": person_phase_id,
                    "status": rows[0]["mapping_status"],
                    "mapping_status": rows[0]["mapping_status"],
                    "reason": rows[0]["reason"],
                    # An ambiguous phase must retain all candidates.  Even
                    # after one candidate was used as the lookup key, the
                    # reader is never handed an arbitrary first target.
                    "targets": [
                        target
                        for item in rows
                        if (target := self._mapping_target(item)) is not None
                    ],
                }
            )
            groups[-1]["mapping_targets"] = groups[-1]["targets"]
        if not groups:
            status = "unmapped"
            reason = "发布版本没有记录该主历史段落的可靠人物对应关系。"
        elif len(groups) > 1 or any(item["status"] == "ambiguous" for item in groups):
            status = "ambiguous"
            reason = "主历史段落对应多个已发布的人物阶段或位置，保留全部候选。"
        else:
            status = groups[0]["status"]
            reason = groups[0]["reason"]
        return {
            "status": status,
            "reason": reason,
            "request": {
                "version": locator["requested_version"],
                "paragraph_id": locator["requested_paragraph_id"],
                "phase_id": phase_id or locator["source_phase_id"],
            },
            "matches": groups,
        }

    # ------------------------------------------------------------------
    # Public repository methods
    # ------------------------------------------------------------------

    def read_metadata(
        self,
        *,
        person_id: Any,
        version: str | None = None,
        main_locator: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if version is not None:
            version = _sha(version, "person-history version")
        person_uuid, canonical_id = _uuid(person_id, "person id")
        person = self._person(canonical_id)
        snapshot = self._load(person=person, person_uuid=person_uuid, version=version)
        if snapshot is None:
            if main_locator is not None:
                raise ReadModelNotFound(
                    "cannot locate a paragraph without a published person history"
                )
            empty = {
                "schema": "chronicle.person-history-metadata",
                "version": READ_VERSION,
                "person_id": person["id"],
                "person": person,
                "status": "empty",
                "empty": True,
                "publication": None,
                "history": None,
                "metadata": None,
            }
            return empty
        projected_phases = [
            self._phase_projection(snapshot, phase)
            for phase in snapshot["phases"]
            if isinstance(phase, dict)
        ]
        first = self._project_paragraphs(snapshot, [snapshot["paragraphs"][0]])[0]
        birth = _date_projection(snapshot["birth"])
        death = _date_projection(snapshot["death"])
        phase_precisions = {phase["time_precision"] for phase in projected_phases}
        phase_precision = (
            next(iter(phase_precisions)) if len(phase_precisions) == 1 else "mixed"
        )
        metadata = {
            "schema": "chronicle.person-history-metadata",
            "version": READ_VERSION,
            "status": "published",
            "empty": False,
            "person_id": snapshot["person_id"],
            "person": snapshot["person"],
            "person_history_version": snapshot["version"],
            "publication_version": snapshot["version"],
            "version_sha": snapshot["version"],
            "catalog_sha": snapshot["catalog_sha"],
            "context_sha256": snapshot["context_sha256"],
            "source_publication_ids": snapshot["source_publication_ids"],
            "source_count": len(snapshot["source_publication_ids"]),
            "coverage": _copy(snapshot["coverage"]),
            "source_coverage": _copy(snapshot["coverage"]),
            "overview": snapshot["overview"],
            "reviewed_overview": snapshot["overview"],
            "birth": birth,
            "death": death,
            "time_precision": {
                "birth": "text" if birth is not None else "unknown",
                "death": "text" if death is not None else "unknown",
                "phases": phase_precision,
            },
            "phases": projected_phases,
            "first_paragraph": first,
            "first_paragraph_id": first["id"],
            "paragraph_count": len(snapshot["paragraphs"]),
            "conclusion_count": len(snapshot["conclusions"]),
            "published_at": snapshot["published_at"],
            "publication_sequence": snapshot["publication_sequence"],
        }
        if main_locator is not None:
            metadata["main_history_mapping"] = self._mapping_for_locator(
                snapshot,
                main_version=main_locator["version"],
                paragraph_id=main_locator["paragraph_id"],
                phase_id=main_locator.get("phase_id"),
            )
            metadata["mapping"] = metadata["main_history_mapping"]
        else:
            metadata["main_history_mapping"] = None
            metadata["mapping"] = None
        return {
            "schema": "chronicle.person-history-metadata",
            "version": READ_VERSION,
            "person_id": snapshot["person_id"],
            "person": snapshot["person"],
            "status": "published",
            "empty": False,
            "publication": metadata,
            "history": metadata,
            "metadata": metadata,
        }

    def read_paragraph_page(
        self,
        *,
        person_id: Any,
        version: str,
        start: int = 0,
        limit: int = 20,
        at: str | None = None,
    ) -> dict[str, Any]:
        version = _sha(version, "person-history version")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ReadModelError("person-history page limit must be between 1 and 50")
        if type(start) is not int or start < 0:
            raise ReadModelError("person-history page start must be nonnegative")
        if at is not None:
            at = _person_paragraph(at)
        _person, snapshot = self._snapshot(person_id, version, required=True)
        assert snapshot is not None
        paragraphs = snapshot["paragraphs"]
        by_id = {
            item.get("id"): item
            for item in paragraphs
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if at is not None:
            if at not in by_id:
                raise ReadModelNotFound("person-history paragraph is outside this fixed version")
            ordinal = int(by_id[at].get("ordinal", 0))
            start = ordinal // limit * limit
        total = len(paragraphs)
        if start >= total:
            raise ReadModelError("person-history page start is outside this fixed version")
        page_raw = paragraphs[start : start + limit]
        projected = self._project_paragraphs(snapshot, page_raw)
        end = start + len(projected)
        return {
            "schema": "chronicle.person-history-page",
            "version": READ_VERSION,
            "person_id": snapshot["person_id"],
            "person_history_version": snapshot["version"],
            "publication_version": snapshot["version"],
            "paragraphs": projected,
            "start": start,
            "total": total,
            "returned": len(projected),
            "first_paragraph_id": projected[0]["id"] if projected else None,
            "last_paragraph_id": projected[-1]["id"] if projected else None,
            "previous_start": max(0, start - limit) if start else None,
            "next_start": end if end < total else None,
            "has_more": end < total,
        }

    def read_conclusion(
        self, *, person_id: Any, version: str, conclusion_id: str
    ) -> dict[str, Any]:
        version = _sha(version, "person-history version")
        conclusion_id = _person_conclusion(conclusion_id)
        _person, snapshot = self._snapshot(person_id, version, required=True)
        assert snapshot is not None
        conclusion = next(
            (
                item
                for item in snapshot["conclusions"]
                if isinstance(item, dict) and item.get("id") == conclusion_id
            ),
            None,
        )
        if conclusion is None:
            raise ReadModelNotFound(
                "person-history conclusion is outside this fixed version"
            )
        if conclusion.get("person_id") != snapshot["person_id"]:
            raise ReadModelInconsistency(
                "published person-history conclusion changes the canonical person"
            )
        entity_ids = [
            value
            for value in conclusion.get("related_entity_ids", [])
            if isinstance(value, str)
        ]
        event_ids = [
            conclusion["event_id"]
        ] if isinstance(conclusion.get("event_id"), str) else []
        source_titles = self._source_titles(
            value.get("publication_id")
            for value in (
                snapshot["evidence"].values()
                if isinstance(snapshot["evidence"], dict)
                else []
            )
        )
        projection = self._conclusion_projection(
            conclusion,
            entity_objects=self._related_objects(entity_ids),
            event_objects=self._related_events(event_ids),
            include_evidence=True,
            evidence_index=snapshot["evidence"],
            source_titles=source_titles,
        )
        return {
            "schema": "chronicle.person-history-conclusion",
            "version": READ_VERSION,
            "person_id": snapshot["person_id"],
            "person_history_version": snapshot["version"],
            "publication_version": snapshot["version"],
            "conclusion": projection,
            "source_citations": projection["evidence"],
        }


__all__ = ["PersonHistoryReadRepository", "READ_VERSION"]
