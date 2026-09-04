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


def _error(status: int, code: str, message: str) -> tuple[int, str, bytes]:
    return status, "application/json; charset=utf-8", _json_bytes(
        {
            "schema": "chronicle.error",
            "version": "0.1",
            "error": {"code": code, "message": message},
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
        "time": record.get("time"),
        "participants": list(record.get("participants") or []),
        "places": list(record.get("places") or []),
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
        return {"bundle": bundle, "ref": ref, "source_title": None, "record": {}}
    return {
        "bundle": bundle,
        "ref": ref,
        "source_title": row[0],
        "source_ref": row[1],
        "record": _record_projection(row[2], link_kind=link_kind),
    }


def _summary(row: tuple, conn) -> dict[str, Any]:
    payload = row[5] if isinstance(row[5], dict) else {}
    suggestion = _suggestion(conn, payload)
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else None
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
        "link_kind": payload.get("link_kind"),
        "candidate_id": payload.get("candidate_id"),
        "resolution_sha256": payload.get("resolution_sha256"),
        "blocking": bool(payload.get("blocking", False)),
        "allowed_decisions": list(payload.get("allowed_decisions") or []),
        "left": payload.get("left"),
        "right": payload.get("right"),
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
    open_count = conn.execute(
        """
        SELECT count(*) FROM chronicle.review_items
        WHERE job_id = %s AND status = 'open' AND payload->>'scope' = 'resolution'
        """,
        (uuid.UUID(item["job_id"]),),
    ).fetchone()[0]
    item["job_open_resolution_reviews"] = int(open_count)
    return item


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
        )
        return 200, "application/json; charset=utf-8", _json_bytes(
            {"schema": "chronicle.review", "version": "0.1", "review": _detail(conn, review_id)}
        )
    raise _NotFound("route not found")
