"""Authenticated Studio projection for C1-T8 resolution ReviewItems.

The Rust Chronicle server owns authentication. This internal sidecar exposes
only the review operations required by C1-T11 and reuses the existing C1-T8
``resolve_publish.resolve_resolution_review`` authority. It does not invent a
second decision vocabulary or derive identity authority from confidence.

Review items are job-scoped, so T11 deliberately reuses the already-authenticated
Rust `/api/v1/studio/jobs/{*rest}` proxy instead of adding a second privileged
server namespace.

Routes:

GET  /api/v1/studio/jobs/reviews[?status=open|resolved|dismissed|all&limit=&offset=]
GET  /api/v1/studio/jobs/reviews/{review_id}
POST /api/v1/studio/jobs/reviews/{review_id}/decision
     {"decision":"...","rationale":"...","confidence":0.0..1.0}
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs

STUDIO_REVIEWS_PREFIX = "/api/v1/studio/jobs/reviews"
_ALLOWED_STATUSES = ("open", "resolved", "dismissed", "all")


class _BadRequest(Exception):
    pass


class _NotFound(Exception):
    pass


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _error(
    status: int, code: str, message: str, *, details: dict[str, Any] | None = None,
) -> tuple[int, str, bytes]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return status, "application/json; charset=utf-8", _json_bytes(
        {
            "schema": "chronicle.error",
            "version": "0.1",
            "error": error,
        }
    )


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _require_uuid(value: str, description: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise _NotFound(f"{description} {value!r} is not a valid UUID") from exc


def _single(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if not values:
        return None
    if len(values) != 1:
        raise _BadRequest(f"query parameter {name} must appear once")
    return values[0]


def _parse_page(query: dict[str, list[str]]) -> tuple[str, int, int]:
    status = _single(query, "status") or "open"
    if status not in _ALLOWED_STATUSES:
        raise _BadRequest(f"status must be one of {list(_ALLOWED_STATUSES)}")
    try:
        limit = int(_single(query, "limit") or "100")
        offset = int(_single(query, "offset") or "0")
    except ValueError as exc:
        raise _BadRequest("limit and offset must be integers") from exc
    if not 1 <= limit <= 200 or offset < 0:
        raise _BadRequest("limit must be within 1..200 and offset must be non-negative")
    return status, limit, offset


def _review_rows(conn, *, status: str, limit: int, offset: int) -> list[tuple]:
    where = "ri.payload->>'scope' = 'resolution'"
    params: list[Any] = []
    if status != "all":
        where += " AND ri.status = %s"
        params.append(status)
    params.extend([limit, offset])
    return conn.execute(
        f"""
        SELECT ri.review_id, ri.job_id, ri.chunk_id, ri.kind, ri.status, ri.payload,
               ri.created_at, ri.resolved_at,
               j.status AS job_status, j.revision_id,
               d.document_id, d.title, r.revision_no, r.filename,
               r.source_sha256, r.language, r.source_label
        FROM chronicle.review_items ri
        JOIN chronicle.ingestion_jobs j ON j.job_id = ri.job_id
        JOIN chronicle.document_revisions r ON r.revision_id = j.revision_id
        JOIN chronicle.documents d ON d.document_id = r.document_id
        WHERE {where}
        ORDER BY CASE ri.status WHEN 'open' THEN 0 ELSE 1 END,
                 ri.created_at, ri.review_id
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    ).fetchall()


def _suggestion(conn, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("review_subject_version"):
        return {
            "decision": payload.get("initial_decision"),
            "confidence": 0.5,
            "rationale": (
                "This review subject aggregates only candidate links that share "
                "already-proven component authority; grouping itself is not an identity decision."
            ),
            "signals": list(payload.get("signals") or []),
        }
    link_kind = payload.get("link_kind")
    table = (
        "chronicle.resolution_entity_links"
        if link_kind == "entity"
        else "chronicle.resolution_event_links"
        if link_kind == "event"
        else None
    )
    if table is None:
        return {
            "decision": payload.get("initial_decision"),
            "confidence": None,
            "rationale": None,
            "signals": list(payload.get("signals") or []),
        }
    row = conn.execute(
        f"""
        SELECT decision, confidence, rationale, signals
        FROM {table}
        WHERE resolution_sha256 = %s AND candidate_id = %s
        """,
        (payload.get("resolution_sha256"), payload.get("candidate_id")),
    ).fetchone()
    if row is None:
        return {
            "decision": payload.get("initial_decision"),
            "confidence": None,
            "rationale": None,
            "signals": list(payload.get("signals") or []),
        }
    return {
        "decision": row[0],
        "confidence": float(row[1]),
        "rationale": row[2],
        "signals": row[3] if isinstance(row[3], list) else list(payload.get("signals") or []),
    }


def _record_projection(record: Any, *, link_kind: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    if link_kind == "entity":
        return {
            "kind": "entity",
            "type": record.get("type"),
            "name": record.get("canonical_name") or record.get("name"),
            "aliases": list(record.get("aliases") or []),
            "mentions": list(record.get("mentions") or []),
        }
    return {
        "kind": "event",
        "type": record.get("type"),
        "title": record.get("title"),
        "summary": record.get("summary"),
        "time": record.get("time"),
        "participants": list(record.get("participants") or []),
        "places": list(record.get("places") or []),
    }


def _entity_display_from_rows(rows: list[tuple]) -> dict[str, dict[str, Any]]:
    """Project staged entity rows to a ref->human-label map without resolving identity."""
    result: dict[str, dict[str, Any]] = {}
    for ref, payload in rows:
        if not isinstance(ref, str) or not isinstance(payload, dict):
            continue
        name = payload.get("canonical_name") or payload.get("name")
        result[ref] = {
            "ref": ref,
            "name": name if isinstance(name, str) and name else ref,
            "type": payload.get("type"),
        }
    return result


def _claim_evidence_from_rows(rows: list[tuple], record_ref: str) -> list[dict[str, Any]]:
    """Return exact staged Claim evidence directly referencing one record.

    This is a read-only evidence projection. It never infers that two records
    are identical and never treats a title/summary as source evidence.
    """
    evidence: list[dict[str, Any]] = []
    for claim_ref, payload in rows:
        if not isinstance(payload, dict):
            continue
        subject = payload.get("subject")
        obj = payload.get("object")
        subject_match = isinstance(subject, dict) and subject.get("ref") == record_ref
        object_match = isinstance(obj, dict) and obj.get("ref") == record_ref
        if not subject_match and not object_match:
            continue
        raw_evidence = payload.get("evidence")
        if not isinstance(raw_evidence, dict):
            continue
        text = raw_evidence.get("text")
        if not isinstance(text, str) or not text:
            continue
        evidence.append(
            {
                "claim_ref": str(claim_ref),
                "relation": "subject" if subject_match else "object",
                "predicate": payload.get("predicate"),
                "text": text,
                "source_ref": raw_evidence.get("source_ref"),
                "locator": raw_evidence.get("locator") if isinstance(raw_evidence.get("locator"), dict) else {},
            }
        )
    return evidence


def _time_display(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    source_calendar = value.get("source_calendar")
    normalized = value.get("normalized")
    source_calendar = source_calendar if isinstance(source_calendar, dict) else {}
    normalized = normalized if isinstance(normalized, dict) else {}
    return {
        "original_text": value.get("original_text"),
        "era": source_calendar.get("era"),
        "era_year": source_calendar.get("era_year"),
        "season": source_calendar.get("season"),
        "month": source_calendar.get("month"),
        "day": source_calendar.get("day"),
        "normalized_year": normalized.get("year"),
        "precision": normalized.get("precision"),
        "approximate": bool(normalized.get("approximate", False)),
    }


def _display_projection(
    record: Any,
    *,
    link_kind: str,
    entity_display: dict[str, dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a human-review display projection from already-staged facts only."""
    if not isinstance(record, dict):
        return {"evidence": evidence}
    if link_kind == "entity":
        name = record.get("canonical_name") or record.get("name")
        return {
            "kind": "entity",
            "type": record.get("type"),
            "name": name,
            "aliases": list(record.get("aliases") or []),
            "mentions": [
                mention.get("text")
                for mention in list(record.get("mentions") or [])
                if isinstance(mention, dict) and isinstance(mention.get("text"), str)
            ],
            "evidence": evidence,
        }

    participants: list[dict[str, Any]] = []
    for participant in list(record.get("participants") or []):
        if not isinstance(participant, dict):
            continue
        ref = participant.get("entity_ref")
        if not isinstance(ref, str):
            continue
        label = entity_display.get(ref, {"ref": ref, "name": ref, "type": None})
        participants.append(
            {
                "ref": ref,
                "name": label.get("name") or ref,
                "type": label.get("type"),
                "role": participant.get("role"),
            }
        )

    places: list[dict[str, Any]] = []
    for ref in list(record.get("places") or []):
        if not isinstance(ref, str):
            continue
        label = entity_display.get(ref, {"ref": ref, "name": ref, "type": None})
        places.append(
            {
                "ref": ref,
                "name": label.get("name") or ref,
                "type": label.get("type"),
            }
        )

    return {
        "kind": "event",
        "type": record.get("type"),
        "name": record.get("title"),
        "summary": record.get("summary"),
        "time": _time_display(record.get("time")),
        "participants": participants,
        "places": places,
        "evidence": evidence,
    }


def _side_context(conn, side: Any, *, link_kind: str) -> dict[str, Any]:
    if not isinstance(side, dict):
        return {}
    bundle, ref = side.get("bundle"), side.get("ref")
    if not isinstance(bundle, str) or not isinstance(ref, str):
        return {}
    table = "chronicle.staged_entities" if link_kind == "entity" else "chronicle.staged_events"
    row = conn.execute(
        f"""
        SELECT b.source_title, b.source_ref, s.payload
        FROM {table} s
        JOIN chronicle.source_bundles b ON b.bundle_label = s.bundle_label
        WHERE s.bundle_label = %s AND s.record_ref = %s
        """,
        (bundle, ref),
    ).fetchone()
    if row is None:
        return {
            "bundle": bundle,
            "ref": ref,
            "source_title": None,
            "record": {},
            "display": {"evidence": []},
        }

    entity_rows = conn.execute(
        """
        SELECT record_ref, payload
        FROM chronicle.staged_entities
        WHERE bundle_label = %s
        ORDER BY record_ref
        """,
        (bundle,),
    ).fetchall()
    claim_rows = conn.execute(
        """
        SELECT record_ref, payload
        FROM chronicle.staged_claims
        WHERE bundle_label = %s
        ORDER BY record_ref
        """,
        (bundle,),
    ).fetchall()
    entity_display = _entity_display_from_rows(entity_rows)
    evidence = _claim_evidence_from_rows(claim_rows, ref)
    return {
        "bundle": bundle,
        "ref": ref,
        "source_title": row[0],
        "source_ref": row[1],
        "record": _record_projection(row[2], link_kind=link_kind),
        "display": _display_projection(
            row[2],
            link_kind=link_kind,
            entity_display=entity_display,
            evidence=evidence,
        ),
    }


def _side_name(conn, side: Any, *, link_kind: str) -> str | None:
    if not isinstance(side, dict):
        return None
    bundle, ref = side.get("bundle"), side.get("ref")
    if not isinstance(bundle, str) or not isinstance(ref, str):
        return None
    table = "chronicle.staged_entities" if link_kind == "entity" else "chronicle.staged_events"
    row = conn.execute(
        f"SELECT payload FROM {table} WHERE bundle_label = %s AND record_ref = %s",
        (bundle, ref),
    ).fetchone()
    if row is None or not isinstance(row[0], dict):
        return None
    record = row[0]
    value = (
        record.get("canonical_name") or record.get("name")
        if link_kind == "entity"
        else record.get("title") or record.get("name")
    )
    return value if isinstance(value, str) and value else None


def _summary(row: tuple, conn) -> dict[str, Any]:
    payload = row[5] if isinstance(row[5], dict) else {}
    suggestion = _suggestion(conn, payload)
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else None
    link_kind = str(payload.get("link_kind") or "")
    return {
        "review_id": str(row[0]),
        "job_id": str(row[1]),
        "chunk_id": str(row[2]) if row[2] is not None else None,
        "kind": row[3],
        "status": row[4],
        "created_at": _iso(row[6]),
        "resolved_at": _iso(row[7]),
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
        "scope": payload.get("scope"),
        "link_kind": link_kind,
        "review_subject_id": payload.get("review_subject_id"),
        "review_subject_version": payload.get("review_subject_version"),
        "member_count": int(payload.get("member_count") or 1),
        "group_count": int(payload.get("group_count") or 1),
        "groups": list(payload.get("groups") or []),
        "members": list(payload.get("members") or []),
        "candidate_id": payload.get("candidate_id"),
        "resolution_sha256": payload.get("resolution_sha256"),
        "blocking": bool(payload.get("blocking", False)),
        "allowed_decisions": list(payload.get("allowed_decisions") or []),
        "left": payload.get("left"),
        "right": payload.get("right"),
        "left_label": _side_name(conn, payload.get("left"), link_kind=link_kind),
        "right_label": _side_name(conn, payload.get("right"), link_kind=link_kind),
        "suggestion": suggestion,
        "decision": decision,
    }


def _detail(conn, review_id: uuid.UUID) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT ri.review_id, ri.job_id, ri.chunk_id, ri.kind, ri.status, ri.payload,
               ri.created_at, ri.resolved_at,
               j.status AS job_status, j.revision_id,
               d.document_id, d.title, r.revision_no, r.filename,
               r.source_sha256, r.language, r.source_label
        FROM chronicle.review_items ri
        JOIN chronicle.ingestion_jobs j ON j.job_id = ri.job_id
        JOIN chronicle.document_revisions r ON r.revision_id = j.revision_id
        JOIN chronicle.documents d ON d.document_id = r.document_id
        WHERE ri.review_id = %s AND ri.payload->>'scope' = 'resolution'
        """,
        (review_id,),
    ).fetchall()
    if not rows:
        raise _NotFound(f"unknown resolution review {review_id}")
    item = _summary(rows[0], conn)
    link_kind = str(item.get("link_kind") or "")
    item["left_context"] = _side_context(conn, item.get("left"), link_kind=link_kind)
    item["right_context"] = _side_context(conn, item.get("right"), link_kind=link_kind)
    members = item.get("members") if isinstance(item.get("members"), list) else []
    left_refs: list[dict[str, Any]] = []
    right_refs: list[dict[str, Any]] = []
    seen_left: set[tuple[str, str]] = set()
    seen_right: set[tuple[str, str]] = set()
    for member in members:
        if not isinstance(member, dict):
            continue
        for side_name, target, seen in (
            ("left", left_refs, seen_left),
            ("right", right_refs, seen_right),
        ):
            side = member.get(side_name)
            if not isinstance(side, dict):
                continue
            bundle, ref = side.get("bundle"), side.get("ref")
            if not isinstance(bundle, str) or not isinstance(ref, str):
                continue
            key = (bundle, ref)
            if key in seen:
                continue
            seen.add(key)
            target.append({"bundle": bundle, "ref": ref})
    if not left_refs and isinstance(item.get("left"), dict):
        left_refs = [item["left"]]
    if not right_refs and isinstance(item.get("right"), dict):
        right_refs = [item["right"]]
    item["left_contexts"] = [
        _side_context(conn, side, link_kind=link_kind) for side in left_refs
    ]
    item["right_contexts"] = [
        _side_context(conn, side, link_kind=link_kind) for side in right_refs
    ]
    review_groups: list[dict[str, Any]] = []
    for raw_group in item.get("groups") or []:
        if not isinstance(raw_group, dict):
            continue
        group_id = raw_group.get("review_group_id")
        members = raw_group.get("members") or []
        if not isinstance(group_id, str) or not isinstance(members, list):
            continue
        group_refs: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for member in members:
            side = member.get("right") if isinstance(member, dict) else None
            if not isinstance(side, dict):
                continue
            bundle, ref = side.get("bundle"), side.get("ref")
            if not isinstance(bundle, str) or not isinstance(ref, str):
                continue
            key = (bundle, ref)
            if key in seen:
                continue
            seen.add(key)
            group_refs.append({"bundle": bundle, "ref": ref})
        review_groups.append(
            {
                "review_group_id": group_id,
                "member_count": int(raw_group.get("member_count") or len(members)),
                "signals": list(raw_group.get("signals") or []),
                "right_contexts": [
                    _side_context(conn, side, link_kind=link_kind)
                    for side in group_refs
                ],
            }
        )
    item["review_groups"] = review_groups
    open_count = conn.execute(
        """
        SELECT count(*) FROM chronicle.review_items
        WHERE job_id = %s AND status = 'open' AND payload->>'scope' = 'resolution'
        """,
        (uuid.UUID(item["job_id"]),),
    ).fetchone()[0]
    item["job_open_resolution_reviews"] = int(open_count)
    return item


def _identity_conflict_details(conn, details: dict[str, Any]) -> dict[str, Any]:
    """Enrich rejected graph refs with the existing source/evidence projection.

    Names only explain the conflict; the persistence guard's canonical IDs
    remain the authority. No review, resolution, or catalog is written here.
    """
    contexts: dict[tuple[str, str], dict[str, Any]] = {}

    def context(side: dict[str, Any]) -> dict[str, Any]:
        key = (side["bundle"], side["ref"])
        if key not in contexts:
            contexts[key] = _side_context(conn, side, link_kind="entity")
        return contexts[key]

    canonical_entities: list[dict[str, Any]] = []
    for canonical_id in details["canonical_ids"]:
        representations = [
            context(side) for side in details["published_refs"]
            if side["canonical_id"] == canonical_id
        ]
        names = {
            item.get("display", {}).get("name") for item in representations
        }
        canonical_entities.append({
            "canonical_id": canonical_id,
            "names": sorted(name for name in names if isinstance(name, str) and name),
            "contexts": representations,
        })
    return {
        **details,
        "canonical_entities": canonical_entities,
        "incoming_contexts": [context(side) for side in details["incoming_refs"]],
        "review_groups": [
            {**group, "right_contexts": [context(side) for side in group["incoming_refs"]]}
            for group in details["review_groups"]
        ],
    }


def dispatch_reviews(
    conn,
    resolve_publish,
    *,
    method: str,
    path: str,
    raw_query: str = "",
    body: bytes = b"",
) -> tuple[int, str, bytes]:
    from common import PersistenceConflict, PersistenceError
    from review_subjects import CanonicalIdentityConflict

    try:
        return _route(
            conn,
            resolve_publish,
            method=method,
            path=path,
            raw_query=raw_query,
            body=body,
        )
    except _BadRequest as exc:
        return _error(400, "bad_request", str(exc))
    except _NotFound as exc:
        return _error(404, "not_found", str(exc))
    except CanonicalIdentityConflict as exc:
        return _error(
            409, exc.code, str(exc), details=_identity_conflict_details(conn, exc.details),
        )
    except PersistenceConflict as exc:
        return _error(409, "conflict", str(exc))
    except PersistenceError as exc:
        message = str(exc)
        if message.startswith("unknown "):
            return _error(404, "not_found", message)
        return _error(400, "bad_request", message)


def _route(conn, resolve_publish, *, method: str, path: str, raw_query: str, body: bytes):
    query = parse_qs(raw_query, keep_blank_values=True)
    if path == STUDIO_REVIEWS_PREFIX:
        if method != "GET":
            raise _BadRequest(f"method {method} is not supported on {path}")
        status, limit, offset = _parse_page(query)
        reviews = [_summary(row, conn) for row in _review_rows(conn, status=status, limit=limit, offset=offset)]
        return 200, "application/json; charset=utf-8", _json_bytes(
            {"schema": "chronicle.review-list", "version": "0.1", "reviews": reviews}
        )

    prefix = STUDIO_REVIEWS_PREFIX + "/"
    if not path.startswith(prefix):
        raise _NotFound("route not found")
    parts = path[len(prefix):].split("/")
    if len(parts) == 1 and parts[0]:
        review_id = _require_uuid(parts[0], "review")
        if method != "GET":
            raise _BadRequest(f"method {method} is not supported on {path}")
        return 200, "application/json; charset=utf-8", _json_bytes(
            {"schema": "chronicle.review", "version": "0.1", "review": _detail(conn, review_id)}
        )
    if len(parts) == 2 and parts[0] and parts[1] == "decision":
        review_id = _require_uuid(parts[0], "review")
        if method != "POST":
            raise _BadRequest(f"method {method} is not supported on {path}")
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _BadRequest(f"request body must be a JSON object: {exc}") from exc
        if not isinstance(payload, dict):
            raise _BadRequest("request body must be a JSON object")
        decision = payload.get("decision")
        rationale = payload.get("rationale")
        confidence = payload.get("confidence", resolve_publish.CONFIDENCE_INITIAL_UNCERTAIN)
        group_decisions = payload.get("group_decisions")
        if group_decisions is not None and not isinstance(group_decisions, list):
            raise _BadRequest("group_decisions must be an array when given")
        if not isinstance(decision, str):
            raise _BadRequest("decision must be a string")
        if not isinstance(rationale, str):
            raise _BadRequest("rationale must be a string")
        resolve_publish.resolve_resolution_review(
            conn,
            review_id=review_id,
            decision=decision,
            rationale=rationale,
            confidence=confidence,
            group_decisions=group_decisions,
        )
        return 200, "application/json; charset=utf-8", _json_bytes(
            {"schema": "chronicle.review", "version": "0.1", "review": _detail(conn, review_id)}
        )
    raise _NotFound("route not found")
