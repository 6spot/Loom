"""Studio read/dispatch surface for C2-R3-T07 person-state review packages.

The queue itself is owned by :mod:`studio_reviews` (``chronicle.studio-review-page``
with ``review_scope``); this module owns the person-state branch of the shared
review routes:

- ``GET  /api/v1/studio/jobs/reviews/{review_id}`` — the versioned
  ``chapter_state_evidence`` package with readable candidate projections;
- ``GET  /api/v1/studio/jobs/reviews/{review_id}/contexts`` — the frozen
  candidate source descriptors (``candidate_id`` optional, bounded pages);
- ``GET  /api/v1/studio/jobs/reviews/{review_id}/sources/{anchor_id}`` — the
  exact revision window/chapter through the shared ``source_context`` reader;
- ``POST /api/v1/studio/jobs/reviews/{review_id}/decision`` — the
  ``{plan_fingerprint, default_assessment, overrides, rationale}`` branch.

The module never invents a second state, source or publication path. The
review payload frozen by C2-R3-T06 is the authority for the candidate set and
its anchors; the accepted ``chronicle.chapter-artifact / 0.3`` is only read to
project human-readable person/office/phase labels. No model, no write, no
canonical identity decision happens on the read path.

``link_kind`` never reaches this branch: it is a resolution-only filter and
``review_scope`` mixing is rejected by the queue parser.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import source_context as _source_context

STUDIO_REVIEWS_PREFIX = "/api/v1/studio/jobs/reviews"

PACKAGE_SCOPE = "person_state"
REVIEW_MODE = "chapter_state_evidence"

DEFAULT_CANDIDATE_LIMIT = 20
MAX_CANDIDATE_LIMIT = 50
DEFAULT_CONTEXT_LIMIT = 50
MAX_CONTEXT_LIMIT = 100
_CANDIDATE_CURSOR_VERSION = 1

#: Candidate kinds whose frozen anchors are mandatory (mirrors T06).
_ANCHOR_KINDS = ("phase", "phase_order", "fact", "continuity", "disagreement")


class PersonStateBadRequest(Exception):
    pass


class PersonStateNotFound(Exception):
    pass


class PersonStateMethodNotAllowed(Exception):
    pass


class PersonStateConflict(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _error(
    status: int, code: str, message: str, *, details: dict[str, Any] | None = None
) -> tuple[int, str, bytes]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return status, "application/json; charset=utf-8", _json_bytes(
        {"schema": "chronicle.error", "version": "0.1", "error": error}
    )


def _single(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if not values:
        return None
    if len(values) != 1:
        raise PersonStateBadRequest(f"query parameter {name} must appear once")
    return values[0]


def _require_review_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise PersonStateNotFound(f"review {value!r} is not a valid UUID") from exc


# ---------------------------------------------------------------------------
# Cursors
# ---------------------------------------------------------------------------


def _b64encode(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(raw: str) -> dict[str, Any]:
    try:
        padded = raw + ("=" * (-len(raw) % 4))
        payload = json.loads(
            base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        )
    except (ValueError, UnicodeDecodeError) as exc:
        raise PersonStateBadRequest(
            f"cursor is not a valid candidate cursor: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise PersonStateBadRequest("cursor is not a valid candidate cursor")
    return payload


def encode_candidate_cursor(
    *, review_id: str, plan_fingerprint: str, offset: int
) -> str:
    return _b64encode(
        {
            "v": _CANDIDATE_CURSOR_VERSION,
            "review_id": str(review_id),
            "plan_fingerprint": str(plan_fingerprint),
            "offset": int(offset),
        }
    )


def decode_candidate_cursor(
    raw: str, *, review_id: str, plan_fingerprint: str
) -> int:
    payload = _b64decode(raw)
    if payload.get("v") != _CANDIDATE_CURSOR_VERSION:
        raise PersonStateBadRequest("candidate cursor version is not supported")
    if str(payload.get("review_id") or "") != str(review_id):
        raise PersonStateBadRequest("candidate cursor belongs to a different review")
    if str(payload.get("plan_fingerprint") or "") != str(plan_fingerprint):
        raise PersonStateBadRequest("candidate cursor belongs to a different plan")
    offset = payload.get("offset")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise PersonStateBadRequest("candidate cursor carries an invalid offset")
    return offset


# ---------------------------------------------------------------------------
# Row / package helpers
# ---------------------------------------------------------------------------

_ROW_QUERY = """
SELECT ri.review_id, ri.job_id, ri.chunk_id, ri.kind, ri.status, ri.payload,
       ri.created_at, ri.resolved_at,
       j.status AS job_status, j.revision_id,
       d.document_id, d.title, r.revision_no, r.filename,
       r.source_sha256, r.language, r.source_label
FROM chronicle.review_items ri
JOIN chronicle.ingestion_jobs j ON j.job_id = ri.job_id
JOIN chronicle.document_revisions r ON r.revision_id = j.revision_id
JOIN chronicle.documents d ON d.document_id = r.document_id
WHERE ri.review_id = %s AND ri.payload->>'scope' = 'person_state'
"""


def _review_row(conn, review_id: uuid.UUID) -> tuple:
    row = conn.execute(_ROW_QUERY, (review_id,)).fetchone()
    if row is None:
        raise PersonStateNotFound(f"unknown person-state review {review_id}")
    payload = row[5] if isinstance(row[5], dict) else {}
    if payload.get("review_mode") != REVIEW_MODE:
        raise PersonStateNotFound(
            f"review {review_id} is not a chapter_state_evidence package"
        )
    return row


def _package_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise PersonStateConflict(
            "inconsistent", "person-state review payload is missing its candidates"
        )
    return [c for c in candidates if isinstance(c, dict)]


def _candidate_by_key(
    payload: dict[str, Any], candidate_id: str
) -> dict[str, Any] | None:
    for candidate in _package_candidates(payload):
        if candidate.get("candidate_key") == candidate_id:
            return candidate
    return None


def _package_anchor_ids(
    payload: dict[str, Any], *, candidate_id: str | None = None
) -> list[str]:
    """Every frozen anchor id of the package, optionally one candidate's."""
    candidates = _package_candidates(payload)
    if candidate_id is not None:
        candidate = _candidate_by_key(payload, candidate_id)
        if candidate is None:
            raise PersonStateNotFound(
                f"unknown candidate {candidate_id!r} for this review"
            )
        candidates = [candidate]
    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        for anchor_id in candidate.get("anchor_ids") or []:
            if isinstance(anchor_id, str) and anchor_id and anchor_id not in seen:
                seen.add(anchor_id)
                ordered.append(anchor_id)
    ordered.sort()
    return ordered


def _load_artifact(
    conn, *, job_id: Any, chapter_id: Any, artifact_sha256: Any
) -> dict[str, Any] | None:
    if not isinstance(chapter_id, str) or not chapter_id:
        return None
    row = conn.execute(
        """
        SELECT payload FROM chronicle.chapter_artifacts
        WHERE job_id = %s AND chapter_id = %s
        """,
        (job_id, chapter_id),
    ).fetchone()
    if row is None or not isinstance(row[0], dict):
        return None
    artifact = row[0]
    if artifact.get("version") != "0.3":
        return None
    if (
        isinstance(artifact_sha256, str)
        and isinstance(artifact.get("artifact_sha256"), str)
        and artifact["artifact_sha256"] != artifact_sha256
    ):
        return None
    return artifact


def _state_index(person_states: Any) -> dict[tuple[str, str], dict[str, Any]]:
    if not isinstance(person_states, dict):
        return {}
    index: dict[tuple[str, str], dict[str, Any]] = {}
    groups = (
        ("phase", "phases", "phase_id"),
        ("phase_order", "phase_orders", "assertion_id"),
        ("unit_phase", "unit_phases", "block_id"),
        ("fact", "facts", "fact_id"),
        ("continuity", "continuities", "assertion_id"),
        ("disagreement", "disagreements", "assertion_id"),
    )
    for kind, collection, id_field in groups:
        for item in person_states.get(collection) or []:
            if isinstance(item, dict) and isinstance(item.get(id_field), str):
                index[(kind, item[id_field])] = item
    return index


def _entity_index(artifact: dict[str, Any]) -> dict[str, str]:
    bundle = artifact.get("candidate", {}).get("bundle")
    entities = bundle.get("entities") if isinstance(bundle, dict) else None
    index: dict[str, str] = {}
    for entity in entities or []:
        if not isinstance(entity, dict) or not isinstance(entity.get("temp_id"), str):
            continue
        name = entity.get("canonical_name") or entity.get("name")
        index[entity["temp_id"]] = name if isinstance(name, str) and name else entity["temp_id"]
    return index


def _source_title(artifact: dict[str, Any] | None) -> str | None:
    if not isinstance(artifact, dict):
        return None
    bundle = artifact.get("candidate", {}).get("bundle")
    source = bundle.get("source") if isinstance(bundle, dict) else None
    title = source.get("title") if isinstance(source, dict) else None
    return title if isinstance(title, str) and title else None


def _ref_name(entities: dict[str, str], ref: Any) -> str | None:
    if isinstance(ref, dict):
        value = ref.get("ref")
        if isinstance(value, str):
            return entities.get(value, value)
    return None


def _anchor_quote(anchors: dict[str, Any], candidate: dict[str, Any]) -> str | None:
    for anchor_id in candidate.get("anchor_ids") or []:
        anchor = anchors.get(anchor_id)
        if isinstance(anchor, dict):
            quote = anchor.get("quote")
            if isinstance(quote, str) and quote:
                return quote
    return None


def _candidate_projection(
    candidate: dict[str, Any],
    *,
    item: dict[str, Any] | None,
    entities: dict[str, str],
    anchors: dict[str, Any],
    source_label: str | None,
) -> dict[str, Any]:
    """Project one frozen candidate into a readable review DTO.

    Only already-frozen data is read: the T06 candidate (kind/dimension/
    operation/qualification/attribution/predicted effect) plus the accepted
    chapter artifact's local state item and the immutable anchors. Missing
    artifact material degrades to null labels, never to a guessed identity.
    """
    item = item if isinstance(item, dict) else {}
    kind = candidate.get("kind")
    phase_refs = [p for p in candidate.get("phase_ids") or [] if isinstance(p, str)]
    person_name: str | None = None
    value: str | None = None
    relation: str | None = candidate.get("relation")
    target: str | None = None

    if kind == "fact":
        person_name = _ref_name(entities, item.get("person_ref"))
        dimension = item.get("dimension")
        relation = item.get("relation")
        if isinstance(relation, str) and relation:
            value = relation
            target = _ref_name(entities, item.get("target_ref"))
        else:
            value = _ref_name(entities, item.get("value_ref"))
        if item.get("phase_ref"):
            phase_refs = [item["phase_ref"]]
    elif kind == "phase":
        label = item.get("label")
        value = label if isinstance(label, str) and label else candidate.get("item_ref")
    elif kind == "phase_order":
        earlier = item.get("earlier_phase_ref")
        later = item.get("later_phase_ref")
        if isinstance(earlier, str) and isinstance(later, str):
            value = f"{earlier} -> {later}"
            phase_refs = [earlier, later]
    elif kind == "unit_phase":
        mode = item.get("mode")
        value = mode if isinstance(mode, str) else None
        phase_refs = [p for p in item.get("phase_refs") or [] if isinstance(p, str)] or phase_refs
    elif kind == "continuity":
        fact_ref = item.get("fact_ref")
        start = item.get("start_phase_ref")
        end = item.get("end_phase_ref")
        value = fact_ref if isinstance(fact_ref, str) else None
        phase_refs = [
            p for p in (start, end) if isinstance(p, str)
        ] or phase_refs
    elif kind == "disagreement":
        topic = item.get("topic")
        value = topic if isinstance(topic, str) else None

    return {
        "candidate_key": candidate.get("candidate_key"),
        "kind": kind,
        "chapter_id": candidate.get("chapter_id"),
        "item_ref": candidate.get("item_ref"),
        "person_id": None,
        "person_name": person_name,
        "dimension": item.get("dimension") if kind == "fact" else None,
        "value": value,
        "relation": relation if kind == "fact" else None,
        "target": target,
        "operation": item.get("operation") if kind == "fact" else None,
        "qualification": item.get("qualification") if kind == "fact" else None,
        "phase_refs": phase_refs,
        "predicted_effect": candidate.get("predicted_effect"),
        "assessment_default": candidate.get("assessment_default"),
        "allowed_assessments": list(candidate.get("allowed_assessments") or []),
        "source_label": source_label or "",
        "quote": _anchor_quote(anchors, candidate) or "",
        "attribution": item.get("attribution")
        or candidate.get("attribution")
        or "narrator",
        "reason_codes": [
            code for code in item.get("reason_codes") or [] if isinstance(code, str)
        ],
    }


def _candidate_projection_context(conn, row: tuple, payload: dict[str, Any]):
    job_id = row[1]
    chapter_id = payload.get("chapter_id")
    artifact = _load_artifact(
        conn,
        job_id=job_id,
        chapter_id=chapter_id,
        artifact_sha256=payload.get("artifact_sha256"),
    )
    state_index = _state_index(artifact.get("person_states") if artifact else None)
    entities = _entity_index(artifact) if artifact else {}
    lookup = _source_context.load_chapter_lookup(conn, job_id=job_id)
    anchors = lookup.get("anchors_by_id") or {}
    source_label = _source_title(artifact) or (row[16] if len(row) > 16 else None)
    return state_index, entities, anchors, source_label


def _decision_summary(payload: dict[str, Any]) -> dict[str, Any] | None:
    decision = payload.get("decision")
    if not isinstance(decision, dict):
        return None
    overrides = decision.get("overrides")
    return {
        "default_assessment": decision.get("default_assessment"),
        "override_count": len(overrides) if isinstance(overrides, list) else 0,
        "rationale": decision.get("rationale"),
        "dismissed": bool(decision.get("dismissed")),
    }


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


def _parse_candidate_page(raw_query: str) -> dict[str, Any]:
    query = parse_qs(raw_query, keep_blank_values=True)
    allowed = frozenset({"limit", "cursor"})
    unknown = sorted(set(query) - allowed)
    if unknown:
        raise PersonStateBadRequest(f"unsupported query parameters: {unknown}")
    try:
        limit = int(_single(query, "limit") or str(DEFAULT_CANDIDATE_LIMIT))
    except ValueError as exc:
        raise PersonStateBadRequest("limit must be an integer") from exc
    if not 1 <= limit <= MAX_CANDIDATE_LIMIT:
        raise PersonStateBadRequest(f"limit must be within 1..{MAX_CANDIDATE_LIMIT}")
    return {"limit": limit, "cursor_raw": _single(query, "cursor")}


def detail(conn, review_id: uuid.UUID, raw_query: str = "") -> dict[str, Any]:
    row = _review_row(conn, review_id)
    payload = row[5] if isinstance(row[5], dict) else {}
    spec = _parse_candidate_page(raw_query)
    fingerprint = str(payload.get("plan_fingerprint") or "")
    offset = 0
    if spec["cursor_raw"] is not None:
        offset = decode_candidate_cursor(
            spec["cursor_raw"], review_id=str(review_id), plan_fingerprint=fingerprint
        )
    candidates = _package_candidates(payload)
    if offset > len(candidates):
        raise PersonStateBadRequest("candidate cursor is past the end of this package")
    page = candidates[offset : offset + spec["limit"]]
    next_offset = offset + len(page)
    has_more = next_offset < len(candidates)
    next_cursor = (
        encode_candidate_cursor(
            review_id=str(review_id), plan_fingerprint=fingerprint, offset=next_offset
        )
        if has_more
        else None
    )

    state_index, entities, anchors, source_label = _candidate_projection_context(
        conn, row, payload
    )
    projected = [
        _candidate_projection(
            candidate,
            item=state_index.get((str(candidate.get("kind")), str(candidate.get("item_ref")))),
            entities=entities,
            anchors=anchors,
            source_label=source_label,
        )
        for candidate in page
    ]

    return {
        "review_id": str(row[0]),
        "job_id": str(row[1]),
        "chunk_id": str(row[2]) if row[2] is not None else None,
        "kind": row[3],
        "status": row[4],
        "created_at": row[6].isoformat() if isinstance(row[6], datetime) else row[6],
        "resolved_at": row[7].isoformat() if isinstance(row[7], datetime) else row[7],
        "job_status": row[8],
        "revision_id": str(row[9]),
        "document": {
            "document_id": str(row[10]),
            "title": row[11],
            "revision_no": int(row[12]),
            "filename": row[13],
            "source_sha256": row[14],
            "language": row[15],
            "source_label": row[16],
        },
        "scope": "person_state",
        "review_mode": REVIEW_MODE,
        "chapter_id": payload.get("chapter_id"),
        "plan_fingerprint": payload.get("plan_fingerprint"),
        "catalog_sha": payload.get("base_catalog_sha"),
        "candidate_count": int(payload.get("candidate_count") or len(candidates)),
        "default_assessment": payload.get("default_assessment"),
        "allowed_assessments": list(payload.get("allowed_assessments") or []),
        "candidates": projected,
        "limit": spec["limit"],
        "cursor": spec["cursor_raw"],
        "next_cursor": next_cursor,
        "has_more": has_more,
        "decision": _decision_summary(payload),
        "left_label": "阶段依据审核",
        "right_label": None,
        "source_entry": {
            "contexts_href": f"{STUDIO_REVIEWS_PREFIX}/{review_id}/contexts",
            "source_href_template": (
                f"{STUDIO_REVIEWS_PREFIX}/{review_id}/sources/{{anchor_id}}"
            ),
            "revision_id": str(row[9]),
            "source_sha256": row[14],
        },
    }


# ---------------------------------------------------------------------------
# Contexts
# ---------------------------------------------------------------------------


def _parse_context_page(raw_query: str) -> dict[str, Any]:
    query = parse_qs(raw_query, keep_blank_values=True)
    allowed = frozenset({"candidate_id", "limit", "cursor"})
    unknown = sorted(set(query) - allowed)
    if unknown:
        raise PersonStateBadRequest(f"unsupported query parameters: {unknown}")
    try:
        limit = int(_single(query, "limit") or str(DEFAULT_CONTEXT_LIMIT))
    except ValueError as exc:
        raise PersonStateBadRequest("limit must be an integer") from exc
    if not 1 <= limit <= MAX_CONTEXT_LIMIT:
        raise PersonStateBadRequest(f"limit must be within 1..{MAX_CONTEXT_LIMIT}")
    return {
        "candidate_id": _single(query, "candidate_id"),
        "limit": limit,
        "cursor_raw": _single(query, "cursor"),
    }


def _anchor_evidence_kind(candidate: dict[str, Any] | None) -> str:
    if isinstance(candidate, dict) and candidate.get("kind") == "fact":
        return "direct_claim"
    return "record_source"


def _anchor_descriptor(
    *,
    review_id: str,
    anchor_id: str,
    anchor: dict[str, Any] | None,
    chapter_info: dict[str, Any] | None,
    artifact: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
) -> dict[str, Any]:
    info = chapter_info if isinstance(chapter_info, dict) else {}
    revision_id = anchor.get("revision_id") if isinstance(anchor, dict) else None
    bundle = ""
    if isinstance(artifact, dict):
        candidate_bundle = artifact.get("candidate", {}).get("bundle")
        if isinstance(candidate_bundle, dict):
            bundle = str(candidate_bundle.get("label") or "")
    anchor_id_value = anchor.get("anchor_id") if isinstance(anchor, dict) else None
    candidate_key = (
        candidate.get("candidate_key") if isinstance(candidate, dict) else None
    )
    available = bool(
        isinstance(anchor, dict) and isinstance(anchor_id_value, str) and info
    )
    unavailable_reason: str | None = None
    if not isinstance(anchor, dict):
        unavailable_reason = "anchor_not_found"
    elif not info:
        unavailable_reason = "legacy_fixture_without_location"
    return {
        "context_id": _context_id(review_id, anchor_id),
        "bundle": bundle,
        "bundle_sha256": None,
        "record_ref": anchor_id,
        "anchor_id": anchor_id,
        "link_kind": "person_state",
        "candidate_keys": [candidate_key] if isinstance(candidate_key, str) else [],
        "job_id": info.get("job_id"),
        "revision_id": str(revision_id) if revision_id is not None else None,
        "chapter_id": anchor.get("chapter_id") if isinstance(anchor, dict) else None,
        "chapter_index": info.get("chapter_index"),
        "chapter_title": info.get("chapter_title"),
        "artifact_sha256": info.get("artifact_sha256"),
        "source_title": _source_title(artifact),
        "source_sha256": anchor.get("source_sha256") if isinstance(anchor, dict) else None,
        "evidence_kinds": [_anchor_evidence_kind(candidate)],
        "available": available,
        "unavailable_reason": unavailable_reason,
        "anchor_count": 1,
        "quote": anchor.get("quote") if isinstance(anchor, dict) else None,
        "start": anchor.get("start") if isinstance(anchor, dict) else None,
        "end": anchor.get("end") if isinstance(anchor, dict) else None,
        "attribution": (
            (candidate.get("attribution") if isinstance(candidate, dict) else None)
            or "narrator"
        ),
        "anchors": [
            {
                "anchor_id": anchor_id_value,
                "chapter_id": anchor.get("chapter_id") if isinstance(anchor, dict) else None,
                "start": anchor.get("start") if isinstance(anchor, dict) else None,
                "end": anchor.get("end") if isinstance(anchor, dict) else None,
                "quote_sha256": anchor.get("quote_sha256") if isinstance(anchor, dict) else None,
            }
        ]
        if isinstance(anchor, dict)
        else [],
    }


def _context_id(review_id: str, anchor_id: str) -> str:
    digest = hashlib.sha256(
        f"{review_id}\x00person-state\x00{anchor_id}".encode("utf-8")
    ).hexdigest()
    return "ctx_" + digest[:16]


def contexts(
    conn, review_id: uuid.UUID, raw_query: str
) -> tuple[int, str, bytes]:
    row = _review_row(conn, review_id)
    payload = row[5] if isinstance(row[5], dict) else {}
    spec = _parse_context_page(raw_query)
    candidate_id = spec["candidate_id"]
    if candidate_id is not None and _candidate_by_key(payload, candidate_id) is None:
        raise PersonStateNotFound(
            f"unknown candidate {candidate_id!r} for this review"
        )
    anchor_ids = _package_anchor_ids(payload, candidate_id=candidate_id)
    offset = 0
    if spec["cursor_raw"] is not None:
        try:
            offset = _source_context.decode_context_cursor(
                spec["cursor_raw"],
                review_id=str(review_id),
                group_id=candidate_id,
            )
        except _source_context.BadCursor as exc:
            raise PersonStateBadRequest(str(exc)) from exc
    if offset > len(anchor_ids):
        raise PersonStateBadRequest("context cursor is past the end of this package")
    lookup = _source_context.load_chapter_lookup(conn, job_id=row[1])
    anchors = lookup.get("anchors_by_id") or {}
    chapters = lookup.get("chapters") or {}
    # Map each anchor to its candidate so one source is not mistaken for a
    # merged person's first reference.
    anchor_candidates: dict[str, dict[str, Any]] = {}
    for entry in _package_candidates(payload):
        for anchor_id in entry.get("anchor_ids") or []:
            if isinstance(anchor_id, str):
                anchor_candidates.setdefault(anchor_id, entry)
    artifact_cache: dict[str, dict[str, Any] | None] = {}
    page_ids = anchor_ids[offset : offset + spec["limit"]]
    items = []
    for anchor_id in page_ids:
        anchor = anchors.get(anchor_id)
        chapter_id = anchor.get("chapter_id") if isinstance(anchor, dict) else None
        chapter_info = chapters.get(chapter_id) if chapter_id else None
        artifact = None
        if isinstance(chapter_info, dict):
            artifact_sha = str(chapter_info.get("artifact_sha256") or "")
            if artifact_sha not in artifact_cache:
                artifact_cache[artifact_sha] = _load_artifact(
                    conn,
                    job_id=row[1],
                    chapter_id=chapter_id,
                    artifact_sha256=chapter_info.get("artifact_sha256"),
                )
            artifact = artifact_cache[artifact_sha]
            if not isinstance(chapter_info.get("job_id"), str):
                chapter_info = {**chapter_info, "job_id": str(row[1])}
        items.append(
            _anchor_descriptor(
                review_id=str(review_id),
                anchor_id=anchor_id,
                anchor=anchor,
                chapter_info=chapter_info,
                artifact=artifact,
                candidate=anchor_candidates.get(anchor_id),
            )
        )
    next_offset = offset + len(page_ids)
    has_more = next_offset < len(anchor_ids)
    next_cursor = (
        _source_context.encode_context_cursor(
            review_id=str(review_id), group_id=candidate_id, offset=next_offset
        )
        if has_more
        else None
    )
    return 200, "application/json; charset=utf-8", _json_bytes(
        {
            "schema": "chronicle.review-source-contexts",
            "version": "0.1",
            "review_id": str(review_id),
            "group_id": candidate_id,
            "candidate_id": candidate_id,
            "total": len(anchor_ids),
            "items": items,
            "has_more": has_more,
            "next_cursor": next_cursor,
        }
    )


# ---------------------------------------------------------------------------
# Sources (reuse the shared source_context reader)
# ---------------------------------------------------------------------------


def _parse_source_query(raw_query: str) -> dict[str, Any]:
    query = parse_qs(raw_query, keep_blank_values=True)
    allowed = frozenset({"view", "cursor", "limit"})
    unknown = sorted(set(query) - allowed)
    if unknown:
        raise PersonStateBadRequest(f"unsupported query parameters: {unknown}")
    view = _single(query, "view") or "window"
    if view not in ("window", "chapter"):
        raise PersonStateBadRequest("view must be window|chapter")
    cursor_raw = _single(query, "cursor")
    limit_raw = _single(query, "limit")
    limit = _source_context.CHAPTER_PAGE_MAX
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except ValueError as exc:
            raise PersonStateBadRequest("limit must be an integer") from exc
        if view != "chapter":
            raise PersonStateBadRequest("limit is only supported for view=chapter")
        if not 1 <= limit <= _source_context.CHAPTER_PAGE_MAX:
            raise PersonStateBadRequest(
                f"limit must be within 1..{_source_context.CHAPTER_PAGE_MAX}"
            )
    return {"view": view, "cursor_raw": cursor_raw, "limit": limit}


def source(
    conn,
    review_id: uuid.UUID,
    anchor_id: str,
    *,
    raw_query: str,
    source_dir: Path | str | None,
) -> tuple[int, str, bytes]:
    spec = _parse_source_query(raw_query)
    row = _review_row(conn, review_id)
    payload = row[5] if isinstance(row[5], dict) else {}
    if anchor_id not in set(_package_anchor_ids(payload)):
        raise PersonStateNotFound(
            f"source anchor {anchor_id!r} is not part of this review"
        )
    lookup = _source_context.load_chapter_lookup(conn, job_id=row[1])
    anchor = (lookup.get("anchors_by_id") or {}).get(anchor_id)
    if anchor is None:
        # The package froze this anchor but the accepted artifact no longer
        # exposes it: fail closed instead of reading a newer revision.
        raise PersonStateConflict(
            "source_mismatch",
            "frozen anchor is missing from the accepted chapter artifact",
        )
    revision_id = anchor.get("revision_id")
    expected_sha = str(anchor.get("source_sha256") or "")
    revision = conn.execute(
        "SELECT storage_key FROM chronicle.document_revisions WHERE revision_id = %s",
        (revision_id,),
    ).fetchone()
    if revision is None or not isinstance(revision[0], str) or not revision[0]:
        raise PersonStateConflict("source_unavailable", "revision source is not configured")
    try:
        text = _source_context.read_revision_text(
            source_dir, revision[0], expected_sha
        )
    except _source_context.SourceUnavailable as exc:
        raise PersonStateConflict("source_unavailable", str(exc)) from exc
    except _source_context.SourceMismatch as exc:
        raise PersonStateConflict("source_mismatch", str(exc)) from exc
    chapter_id = anchor.get("chapter_id")
    if not isinstance(chapter_id, str) or not chapter_id:
        raise PersonStateConflict("source_unavailable", "anchor has no chapter binding")
    try:
        bounds = _source_context.chapter_bounds(lookup, chapter_id)
    except _source_context.SourceUnavailable as exc:
        raise PersonStateConflict("source_unavailable", str(exc)) from exc
    chapter_start, chapter_end = bounds
    if not (0 <= chapter_start < chapter_end <= len(text)):
        raise PersonStateConflict(
            "source_mismatch", "recorded chapter boundary is outside this revision text"
        )
    chapter_text = text[chapter_start:chapter_end]
    try:
        _source_context.verify_anchor_in_chapter(anchor, chapter_text)
    except _source_context.SourceMismatch as exc:
        raise PersonStateConflict("source_mismatch", str(exc)) from exc
    anchor_start, anchor_end = int(anchor["start"]), int(anchor["end"])
    rev_start, rev_end = chapter_start + anchor_start, chapter_start + anchor_end
    if spec["view"] == "window":
        if spec["cursor_raw"] is not None:
            raise PersonStateBadRequest("cursor is only supported for view=chapter")
        window = _source_context.window_in_chapter(chapter_text, anchor_start, anchor_end)
        return 200, "application/json; charset=utf-8", _json_bytes(
            {
                "schema": "chronicle.review-source",
                "version": "0.1",
                "review_id": str(review_id),
                "anchor_id": anchor_id,
                "view": "window",
                "revision_id": str(revision_id),
                "source_sha256": expected_sha,
                "chapter_id": chapter_id,
                "bundle": "",
                "record_ref": anchor_id,
                "bounds": {
                    "start": rev_start,
                    "end": rev_end,
                    "slice_start": chapter_start + window["slice_start"],
                    "slice_end": chapter_start + window["slice_end"],
                    "chapter_start": chapter_start,
                    "chapter_end": chapter_end,
                    "chapter_length": len(chapter_text),
                },
                "source_hash": _source_context.sha256_text(text),
                "chapter_hash": _source_context.sha256_text(chapter_text),
                "text": window["text"],
                "segments": window["segments"],
                "has_more": False,
                "next_cursor": None,
            }
        )
    offset = 0
    if spec["cursor_raw"] is not None:
        try:
            offset = _source_context.decode_source_cursor(
                spec["cursor_raw"],
                review_id=str(review_id),
                anchor_id=anchor_id,
                view=spec["view"],
            )
        except _source_context.BadCursor as exc:
            raise PersonStateBadRequest(str(exc)) from exc
    if offset > len(chapter_text):
        raise PersonStateBadRequest("chapter cursor is past the end of this chapter")
    try:
        page = _source_context.chapter_page_for(
            chapter_text, offset, limit=spec["limit"], anchor=anchor
        )
    except _source_context.BadCursor as exc:
        raise PersonStateBadRequest(str(exc)) from exc
    next_cursor = (
        _source_context.encode_source_cursor(
            review_id=str(review_id),
            anchor_id=anchor_id,
            view=spec["view"],
            offset=page["slice_end"],
        )
        if page["has_more"]
        else None
    )
    return 200, "application/json; charset=utf-8", _json_bytes(
        {
            "schema": "chronicle.review-source",
            "version": "0.1",
            "review_id": str(review_id),
            "anchor_id": anchor_id,
            "view": "chapter",
            "revision_id": str(revision_id),
            "source_sha256": expected_sha,
            "chapter_id": chapter_id,
            "bundle": "",
            "record_ref": anchor_id,
            "bounds": {
                "start": rev_start,
                "end": rev_end,
                "slice_start": chapter_start + page["slice_start"],
                "slice_end": chapter_start + page["slice_end"],
                "chapter_start": chapter_start,
                "chapter_end": chapter_end,
                "chapter_length": len(chapter_text),
            },
            "source_hash": _source_context.sha256_text(text),
            "chapter_hash": _source_context.sha256_text(chapter_text),
            "text": page["text"],
            "segments": page["segments"],
            "has_more": page["has_more"],
            "next_cursor": next_cursor,
        }
    )


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

_DECISION_FIELDS = frozenset(
    {"plan_fingerprint", "default_assessment", "overrides", "rationale", "dismiss"}
)


def _normalize_overrides(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise PersonStateBadRequest("overrides must be an array")
    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise PersonStateBadRequest(f"overrides[{index}] must be an object")
        candidate_id = entry.get("candidate_id") or entry.get("candidate_key")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise PersonStateBadRequest(
                f"overrides[{index}] requires candidate_id or candidate_key"
            )
        record = {
            "candidate_id": candidate_id,
            "assessment": entry.get("assessment"),
            "rationale": entry.get("rationale"),
        }
        normalized.append(record)
    return normalized


def decision(conn, review_id: uuid.UUID, *, body: bytes) -> tuple[int, str, bytes]:
    try:
        payload_in = json.loads(body.decode("utf-8")) if body else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersonStateBadRequest(
            f"request body must be a JSON object: {exc}"
        ) from exc
    if not isinstance(payload_in, dict):
        raise PersonStateBadRequest("request body must be a JSON object")
    unknown = sorted(set(payload_in) - _DECISION_FIELDS)
    if unknown:
        raise PersonStateBadRequest(f"unknown person-state decision field {unknown[0]!r}")
    dismiss = payload_in.get("dismiss", False)
    if not isinstance(dismiss, bool):
        raise PersonStateBadRequest("dismiss must be a boolean when given")

    import person_state_review as _review

    row = _review_row(conn, review_id)
    payload = row[5] if isinstance(row[5], dict) else {}
    stored_fingerprint = payload.get("plan_fingerprint")
    submitted = payload_in.get("plan_fingerprint")
    if submitted is not None and submitted != stored_fingerprint:
        raise PersonStateConflict(
            "plan_drift",
            "person-state review was frozen against a different plan",
        )
    if row[4] != "open":
        raise PersonStateConflict(
            "conflict",
            f"person-state review {review_id} is already {row[4]!r} (duplicate submission)",
        )
    with conn.transaction():
        locked = conn.execute(
            "SELECT status, payload FROM chronicle.review_items"
            " WHERE review_id = %s FOR UPDATE",
            (review_id,),
        ).fetchone()
        if locked is None:
            raise PersonStateNotFound(f"unknown person-state review {review_id}")
        status, raw_payload = locked
        locked_payload = raw_payload if isinstance(raw_payload, dict) else {}
        if locked_payload.get("plan_fingerprint") != stored_fingerprint:
            raise PersonStateConflict(
                "plan_drift", "frozen person-state package changed during review"
            )
        if status != "open":
            raise PersonStateConflict(
                "conflict",
                f"person-state review {review_id} is already {status!r} (duplicate submission)",
            )
        if dismiss:
            record = {
                "plan_fingerprint": stored_fingerprint,
                "default_assessment": _review.DEFAULT_ASSESSMENT,
                "overrides": [],
                "rationale": "dismissed; the candidates stay uncertain and reviewable.",
                "dismissed": True,
                "decisions": {
                    candidate["candidate_key"]: {
                        "assessment": _review.DEFAULT_ASSESSMENT,
                        "rationale": "dismissed; kept explicitly uncertain.",
                        "override": False,
                    }
                    for candidate in _package_candidates(locked_payload)
                },
            }
            terminal = "dismissed"
        else:
            decision_in = {
                "default_assessment": payload_in.get("default_assessment"),
                "rationale": payload_in.get("rationale", ""),
                "overrides": _normalize_overrides(payload_in.get("overrides")),
            }
            normalized = _review.normalize_person_state_decision(
                locked_payload,
                decision_in,
                plan_fingerprint=str(stored_fingerprint),
            )
            record = {**normalized, "dismissed": False}
            terminal = "resolved"
        stored = dict(locked_payload)
        stored["decision"] = record
        from psycopg.types.json import Jsonb

        conn.execute(
            "UPDATE chronicle.review_items SET payload = %s WHERE review_id = %s",
            (Jsonb(stored), review_id),
        )
        import control_plane

        control_plane.resolve_review_item(conn, review_id=review_id, status=terminal)
    return 200, "application/json; charset=utf-8", _json_bytes(
        {"schema": "chronicle.review", "version": "0.1", "review": detail(conn, review_id)}
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_ROUTES = frozenset({"detail", "contexts", "sources", "decision"})


def dispatch_person_state_review(
    conn,
    review_id: uuid.UUID,
    *,
    method: str,
    route: str,
    raw_query: str = "",
    body: bytes = b"",
    source_dir: Path | str | None = None,
    anchor_id: str | None = None,
) -> tuple[int, str, bytes]:
    """Handle one person-state review route, mapping errors to HTTP status."""
    from common import PersistenceConflict, PersistenceError

    try:
        if route not in _ROUTES:
            raise PersonStateNotFound("route not found")
        if route in ("detail", "contexts", "sources"):
            if method != "GET":
                raise PersonStateMethodNotAllowed(
                    f"method {method} is not supported on this person-state route"
                )
        elif method != "POST":
            raise PersonStateBadRequest(
                f"method {method} is not supported on this person-state route"
            )
        if route == "detail":
            return 200, "application/json; charset=utf-8", _json_bytes(
                {
                    "schema": "chronicle.review",
                    "version": "0.1",
                    "review": detail(conn, review_id, raw_query),
                }
            )
        if route == "contexts":
            return contexts(conn, review_id, raw_query)
        if route == "sources":
            if not anchor_id:
                raise PersonStateNotFound("source anchor is missing")
            return source(
                conn, review_id, anchor_id, raw_query=raw_query, source_dir=source_dir
            )
        return decision(conn, review_id, body=body)
    except PersonStateBadRequest as exc:
        return _error(400, "bad_request", str(exc))
    except PersonStateNotFound as exc:
        return _error(404, "not_found", str(exc))
    except PersonStateMethodNotAllowed as exc:
        return _error(405, "method_not_allowed", str(exc))
    except PersonStateConflict as exc:
        return _error(409, exc.code, str(exc))
    except PersistenceConflict as exc:
        return _error(409, "conflict", str(exc))
    except PersistenceError as exc:
        message = str(exc)
        if message.startswith("unknown "):
            return _error(404, "not_found", message)
        return _error(400, "bad_request", message)


__all__ = [
    "STUDIO_REVIEWS_PREFIX",
    "PACKAGE_SCOPE",
    "REVIEW_MODE",
    "contexts",
    "decision",
    "decode_candidate_cursor",
    "detail",
    "dispatch_person_state_review",
    "encode_candidate_cursor",
    "source",
]
