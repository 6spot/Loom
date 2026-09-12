"""Authenticated Studio projection for C1-T8 resolution ReviewItems.

The Rust Chronicle server owns authentication. This internal sidecar exposes
only the review operations required by C1-T11 and reuses the existing C1-T8
``resolve_publish.resolve_resolution_review`` authority. It does not invent a
second decision vocabulary or derive identity authority from confidence.

Review items are job-scoped, so T11 deliberately reuses the already-authenticated
Rust `/api/v1/studio/jobs/{*rest}` proxy instead of adding a second privileged
server namespace.

Routes:

GET  /api/v1/studio/jobs/reviews[?status=open|resolved|dismissed|all&job_id=&link_kind=entity|event&limit=&cursor=]
GET  /api/v1/studio/jobs/reviews/{review_id}
POST /api/v1/studio/jobs/reviews/{review_id}/decision
     {"decision":"...","rationale":"...","confidence":0.0..1.0}

The list endpoint is the C2-R1 review-workflow queue API
(``chronicle.studio-review-page / 0.2``). It pages one ``resolution`` scope
with a stable ``(created_at, review_id)`` keyset only: there is no offset
mode, rows are never ordered by the mutable ``status``, and ``limit + 1``
decides the next cursor. ``open_count`` is the whole-scope open total
observed in the same read transaction, not a frozen denominator, so a late
row inserted before an old cursor is found again by re-reading from the
head of the same scope.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import source_context as _source_context

_STUDIO_PERSON_STATES = None


def _person_states():
    """Lazy module handle so read_api can load without persistence imports."""
    global _STUDIO_PERSON_STATES
    if _STUDIO_PERSON_STATES is None:
        import studio_person_states as _module

        _STUDIO_PERSON_STATES = _module
    return _STUDIO_PERSON_STATES


STUDIO_REVIEWS_PREFIX = "/api/v1/studio/jobs/reviews"
_ALLOWED_STATUSES = ("open", "resolved", "dismissed", "all")
_ALLOWED_LINK_KINDS = ("entity", "event")
_ALLOWED_LIST_PARAMS = frozenset(
    {"status", "job_id", "link_kind", "review_scope", "limit", "cursor"}
)
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 100
_CURSOR_VERSION = 1
# Fingerprint algorithm marker. The frozen-plan fields below follow
# chapter-production §6 (version, job/revision, assembled/base-catalog
# hashes when the plan carries them, sorted resolution/candidate/member/
# group identity); mutable decision/status/resolved_at never enter it.
_FINGERPRINT_ALGORITHM = "studio-review-page-fingerprint-v1"
_LEGACY_PLAN_VERSION = "c1-frozen-review-plan-v1"


class _BadRequest(Exception):
    pass


class _NotFound(Exception):
    pass


class _Conflict(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _MethodNotAllowed(Exception):
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


def _parse_uuid_param(raw: str | None, name: str) -> uuid.UUID | None:
    if raw is None:
        return None
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError) as exc:
        raise _BadRequest(f"{name} must be a UUID") from exc


def _parse_page(query: dict[str, list[str]]) -> dict[str, Any]:
    from common import PersistenceError
    from person_state_contract import assert_link_kind_scope, normalize_review_scope

    unknown = sorted(set(query) - _ALLOWED_LIST_PARAMS)
    if unknown:
        raise _BadRequest(f"unsupported query parameters: {unknown}")
    status = _single(query, "status") or "open"
    if status not in _ALLOWED_STATUSES:
        raise _BadRequest(f"status must be one of {list(_ALLOWED_STATUSES)}")
    link_kind = _single(query, "link_kind")
    if link_kind is not None and link_kind not in _ALLOWED_LINK_KINDS:
        raise _BadRequest(f"link_kind must be one of {list(_ALLOWED_LINK_KINDS)}")
    try:
        review_scope = normalize_review_scope(_single(query, "review_scope"))
        assert_link_kind_scope(review_scope, link_kind)
    except PersistenceError as exc:
        raise _BadRequest(str(exc)) from exc
    job_id = _parse_uuid_param(_single(query, "job_id"), "job_id")
    try:
        limit = int(_single(query, "limit") or str(_DEFAULT_LIMIT))
    except ValueError as exc:
        raise _BadRequest("limit must be an integer") from exc
    if not 1 <= limit <= _MAX_LIMIT:
        raise _BadRequest(f"limit must be within 1..{_MAX_LIMIT}")
    cursor_raw = _single(query, "cursor")
    cursor = _decode_cursor(cursor_raw) if cursor_raw is not None else None
    if cursor is not None and (
        cursor["status"] != status
        or cursor["job_id"] != (str(job_id) if job_id is not None else None)
        or cursor["link_kind"] != link_kind
        or cursor["review_scope"] != review_scope
    ):
        raise _BadRequest("cursor was issued for a different filter scope and cannot be reused")
    return {
        "status": status,
        "job_id": job_id,
        "link_kind": link_kind,
        "review_scope": review_scope,
        "limit": limit,
        "cursor": cursor,
    }


def _encode_cursor(
    *, review_scope: str, status: str, job_id: uuid.UUID | None,
    link_kind: str | None, created_at: Any, review_id: uuid.UUID,
) -> str:
    payload = {
        "v": _CURSOR_VERSION,
        "review_scope": review_scope,
        "status": status,
        "job_id": str(job_id) if job_id is not None else None,
        "link_kind": link_kind,
        "created_at": _iso(created_at),
        "review_id": str(review_id),
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(raw: str) -> dict[str, Any]:
    from person_state_contract import REVIEW_SCOPES

    try:
        padded = raw + ("=" * (-len(raw) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise _BadRequest(f"cursor is not a valid review-page cursor: {exc}") from exc
    if not isinstance(payload, dict):
        raise _BadRequest("cursor is not a valid review-page cursor")
    if payload.get("v") != _CURSOR_VERSION:
        raise _BadRequest("cursor version is not supported")
    if payload.get("status") not in _ALLOWED_STATUSES:
        raise _BadRequest("cursor carries an unsupported status scope")
    link_kind = payload.get("link_kind")
    if link_kind is not None and link_kind not in _ALLOWED_LINK_KINDS:
        raise _BadRequest("cursor carries an unsupported link_kind scope")
    review_scope_raw = payload.get("review_scope")
    if review_scope_raw is None:
        review_scope_raw = "resolution"
    if review_scope_raw not in REVIEW_SCOPES:
        raise _BadRequest("cursor carries an unsupported review_scope")
    job_id_raw = payload.get("job_id")
    job_id: str | None = None
    if job_id_raw is not None:
        try:
            job_id = str(uuid.UUID(job_id_raw))
        except (ValueError, AttributeError, TypeError) as exc:
            raise _BadRequest("cursor carries an invalid job_id scope") from exc
    created_raw = payload.get("created_at")
    if not isinstance(created_raw, str) or not created_raw:
        raise _BadRequest("cursor carries an invalid sort key")
    try:
        review_id = uuid.UUID(payload.get("review_id"))
    except (ValueError, AttributeError, TypeError) as exc:
        raise _BadRequest("cursor carries an invalid sort key") from exc
    try:
        created_at = datetime.fromisoformat(created_raw)
    except ValueError as exc:
        raise _BadRequest("cursor carries an invalid sort key") from exc
    return {
        "review_scope": review_scope_raw,
        "status": payload.get("status"),
        "job_id": job_id,
        "link_kind": link_kind,
        "created_at": created_at,
        "review_id": review_id,
    }


def _scope_filter(
    spec: dict[str, Any], *, include_status: bool, alias: str = "ri",
) -> tuple[str, list[Any]]:
    from person_state_contract import review_scope_covers

    covered = [
        scope
        for scope in ("resolution", "person_state", "narrative")
        if review_scope_covers(spec["review_scope"], scope)
    ]
    placeholders = ", ".join(["%s"] * len(covered))
    where = f"{alias}.payload->>'scope' IN ({placeholders})"
    params: list[Any] = list(covered)
    if include_status and spec["status"] != "all":
        where += f" AND {alias}.status = %s"
        params.append(spec["status"])
    if spec["job_id"] is not None:
        where += f" AND {alias}.job_id = %s"
        params.append(spec["job_id"])
    if spec["link_kind"] is not None:
        where += f" AND {alias}.payload->>'link_kind' = %s"
        params.append(spec["link_kind"])
    return where, params


def _review_rows(conn, *, spec: dict[str, Any]) -> list[tuple]:
    where, params = _scope_filter(spec, include_status=True)
    cursor = spec["cursor"]
    if cursor is not None:
        where += " AND (ri.created_at, ri.review_id) > (%s, %s)"
        params.extend([cursor["created_at"], cursor["review_id"]])
    params.append(spec["limit"] + 1)
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
        ORDER BY ri.created_at, ri.review_id
        LIMIT %s
        """,
        tuple(params),
    ).fetchall()


def _scope_open_count(conn, *, spec: dict[str, Any]) -> int:
    where, params = _scope_filter(spec, include_status=False)
    row = conn.execute(
        f"""
        SELECT count(*) FROM chronicle.review_items ri
        WHERE {where} AND ri.status = 'open'
        """,
        tuple(params),
    ).fetchone()
    return int(row[0])


def _candidate_key_of(payload: dict[str, Any], index: int) -> str:
    if payload.get("scope") == "narrative":
        return f"narrative:{payload['narrative_kind']}:{payload['candidate_sha']}"
    key = payload.get("candidate_key")
    if isinstance(key, str) and key:
        return key
    resolution_sha = payload.get("resolution_sha256")
    candidate_id = payload.get("candidate_id")
    if isinstance(resolution_sha, str) and isinstance(candidate_id, str):
        return f"{resolution_sha}:{candidate_id}"
    return f"legacy-item-{index}"


def _immutable_candidate_entry(payload: dict[str, Any], index: int) -> dict[str, Any]:
    if payload.get("scope") == "narrative":
        return {"candidate_key": _candidate_key_of(payload, index), "scope": "narrative",
                "narrative_kind": payload["narrative_kind"], "candidate_sha": payload["candidate_sha"]}
    if payload.get("scope") == "person_state":
        candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
        candidate_keys = sorted(
            str(candidate.get("candidate_key"))
            for candidate in candidates
            if isinstance(candidate, dict) and isinstance(candidate.get("candidate_key"), str)
        )
        return {
            "candidate_key": f"person_state:{payload.get('plan_fingerprint')}",
            "scope": "person_state",
            "plan_fingerprint": payload.get("plan_fingerprint"),
            "chapter_id": payload.get("chapter_id"),
            "candidate_keys": candidate_keys,
        }

    def _ref(value: Any) -> dict[str, str] | None:
        if not isinstance(value, dict):
            return None
        bundle, ref = value.get("bundle"), value.get("ref")
        if not isinstance(bundle, str) or not isinstance(ref, str):
            return None
        return {"bundle": bundle, "ref": ref}

    members = payload.get("members") if isinstance(payload.get("members"), list) else []
    member_keys: list[str] = []
    member_refs: list[str] = []
    for position, member in enumerate(members):
        if not isinstance(member, dict):
            continue
        key = member.get("candidate_key")
        if isinstance(key, str) and key:
            member_keys.append(key)
        else:
            resolution_sha = member.get("resolution_sha256")
            candidate_id = member.get("candidate_id")
            if isinstance(resolution_sha, str) and isinstance(candidate_id, str):
                member_keys.append(f"{resolution_sha}:{candidate_id}")
        for side in (member.get("left"), member.get("right")):
            ref = _ref(side)
            if ref is not None:
                member_refs.append(f"{ref['bundle']}:{ref['ref']}")
    groups = payload.get("groups") if isinstance(payload.get("groups"), list) else []
    group_ids = sorted(
        str(group.get("review_group_id"))
        for group in groups
        if isinstance(group, dict) and isinstance(group.get("review_group_id"), str)
    )
    left, right = _ref(payload.get("left")), _ref(payload.get("right"))
    return {
        "candidate_key": _candidate_key_of(payload, index),
        "link_kind": payload.get("link_kind"),
        "left": left,
        "right": right,
        "review_subject_id": payload.get("review_subject_id"),
        "review_subject_version": payload.get("review_subject_version"),
        "plan_version": payload.get("plan_version"),
        "member_keys": sorted(member_keys),
        "member_refs": sorted(set(member_refs)),
        "group_ids": group_ids,
    }


def _plan_fingerprint(
    conn, *, spec: dict[str, Any],
) -> str:
    """Fingerprint the frozen plan behind one resolution scope.

    Only immutable identity enters: fingerprint algorithm marker, observed
    plan versions, job/revision ids, assembled/base-catalog hashes when the
    plan carries them, and the sorted per-candidate identity above. The
    persisted ``decision``, row ``status`` and ``resolved_at`` never enter,
    so resolving items does not rotate the fingerprint that review drafts
    use as their ``(review_id, plan_fingerprint)`` key. Existing C1 frozen
    plans hash under the legacy marker; a ``c2r1-review-plan-v1`` payload
    contributes its defined fields without any review_subjects change here.
    """
    where, params = _scope_filter(spec, include_status=False)
    rows = conn.execute(
        f"""
        SELECT ri.payload, ri.job_id, j.revision_id
        FROM chronicle.review_items ri
        JOIN chronicle.ingestion_jobs j ON j.job_id = ri.job_id
        WHERE {where}
        ORDER BY ri.created_at, ri.review_id
        """,
        tuple(params),
    ).fetchall()
    plan_versions: set[str] = set()
    assembled: set[str] = set()
    base_catalog: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        payload = row[0] if isinstance(row[0], dict) else {}
        version = payload.get("plan_version")
        if isinstance(version, str) and version:
            plan_versions.add(version)
        elif isinstance(payload.get("review_subject_version"), str):
            plan_versions.add(str(payload.get("review_subject_version")))
        else:
            plan_versions.add(_LEGACY_PLAN_VERSION)
        for field, target in (
            ("assembled_bundle_sha256", assembled),
            ("base_catalog_sha256", base_catalog),
        ):
            value = payload.get(field)
            if isinstance(value, str) and value:
                target.add(value)
        if payload.get("scope") == "person_state":
            base_catalog_value = payload.get("base_catalog_sha")
            if isinstance(base_catalog_value, str) and base_catalog_value:
                base_catalog.add(base_catalog_value)
        candidates.append(_immutable_candidate_entry(payload, index))
    document = {
        "algorithm": _FINGERPRINT_ALGORITHM,
        "plan_versions": sorted(plan_versions),
        "job_ids": sorted({str(row[1]) for row in rows}),
        "revision_ids": sorted({str(row[2]) for row in rows}),
        "assembled_bundle_sha256": sorted(assembled),
        "base_catalog_sha256": sorted(base_catalog),
        "candidates": sorted(candidates, key=lambda item: json.dumps(item, sort_keys=True)),
    }
    canonical = json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


def _summary(row: tuple, conn, *, plan_fingerprint: str | None = None) -> dict[str, Any]:
    payload = row[5] if isinstance(row[5], dict) else {}
    suggestion = _suggestion(conn, payload)
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else None
    link_kind = str(payload.get("link_kind") or "")
    item = {
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
    if plan_fingerprint is not None:
        item["plan_fingerprint"] = plan_fingerprint
    if payload.get("scope") == "narrative":
        item["narrative_kind"] = payload["narrative_kind"]
        item["candidate_sha"] = payload["candidate_sha"]
        item["left_label"] = "多史料事实核对" if payload["narrative_kind"] == "facts" else "综合正文审核"
        item["right_label"] = None
        item["decision"] = {key: decision[key] for key in ("decision", "rationale", "content_sha") if key in decision} if decision else None
    if payload.get("scope") == "person_state":
        candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
        overrides = decision.get("overrides") if isinstance(decision, dict) else None
        item["review_mode"] = payload.get("review_mode")
        item["chapter_id"] = payload.get("chapter_id")
        item["candidate_count"] = int(payload.get("candidate_count") or len(candidates))
        item["default_assessment"] = payload.get("default_assessment")
        item["allowed_assessments"] = list(payload.get("allowed_assessments") or [])
        item["plan_fingerprint"] = payload.get("plan_fingerprint")
        item["left_label"] = "阶段依据审核"
        item["right_label"] = None
        item["decision"] = (
            {
                "default_assessment": decision.get("default_assessment"),
                "override_count": len(overrides) if isinstance(overrides, list) else 0,
                "rationale": decision.get("rationale"),
                "dismissed": bool(decision.get("dismissed")),
            }
            if decision
            else None
        )
    return item


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
        WHERE ri.review_id = %s AND ri.payload->>'scope' IN ('resolution', 'narrative', 'person_state')
        """,
        (review_id,),
    ).fetchall()
    if not rows:
        raise _NotFound(f"unknown review {review_id}")
    item = _summary(rows[0], conn)
    if item["scope"] == "person_state":
        return _person_states().detail(conn, review_id)
    if item["scope"] == "narrative":
        import narrative_store
        item["narrative"] = narrative_store.review_detail(conn, review_id)
        if item["narrative"] is None:
            raise _NotFound("narrative candidate unavailable")
        if item["narrative"]["kind"] == "prose":
            item["narrative"]["facts"] = narrative_store.approved_content(
                narrative_store.read_candidate(conn, item["job_id"], "facts"))
        return item
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


def _clear_source_context_cache() -> None:
    """Test hook: kept for compatibility; lookups are per-request (no staleness)."""


def _review_identity(conn, review_id: uuid.UUID) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT ri.review_id, ri.job_id, ri.payload,
               j.revision_id,
               d.document_id, d.title,
               r.revision_no, r.filename, r.source_sha256, r.storage_key,
               r.language, r.source_label
        FROM chronicle.review_items ri
        JOIN chronicle.ingestion_jobs j ON j.job_id = ri.job_id
        JOIN chronicle.document_revisions r ON r.revision_id = j.revision_id
        JOIN chronicle.documents d ON d.document_id = r.document_id
        WHERE ri.review_id = %s AND ri.payload->>'scope' = 'resolution'
        """,
        (review_id,),
    ).fetchone()
    if row is None:
        raise _NotFound(f"unknown resolution review {review_id}")
    return {
        "review_id": row[0],
        "job_id": row[1],
        "payload": row[2] if isinstance(row[2], dict) else {},
        "revision_id": row[3],
        "document_id": row[4],
        "document_title": row[5],
        "revision_no": row[6],
        "filename": row[7],
        "source_sha256": row[8],
        "storage_key": row[9],
        "language": row[10],
        "source_label": row[11],
    }


class _SourceRequestCache:
    """Per-request source caches (no cross-request staleness).

    Holds bundle owners resolved through the worker's ``source-bundle``
    ingestion outputs, one chapter lookup per owner job, and the exact
    revision storage rows those owners point at. Loading once per request
    avoids rescanning whole bundles for every group/member.
    """

    def __init__(self, conn) -> None:
        self.conn = conn
        self.lookups: dict[str, Any] = {}
        self.bundles: dict[str, tuple[str | None, str | None]] = {}
        self.owners: dict[str, dict[str, Any] | None] = {}
        self.revisions: dict[str, dict[str, Any] | None] = {}

    def owner_of(self, bundle: str) -> dict[str, Any] | None:
        if bundle not in self.owners:
            self.owners[bundle] = _source_context.resolve_bundle_owner(
                self.conn, bundle
            )
        return self.owners[bundle]

    def lookup_for(self, job_id: Any) -> dict[str, Any]:
        key = str(job_id)
        cached = self.lookups.get(key)
        if cached is None:
            cached = _source_context.load_chapter_lookup(self.conn, job_id=job_id)
            self.lookups[key] = cached
        return cached

    def revision_source(self, revision_id: Any) -> dict[str, Any] | None:
        key = str(revision_id)
        if key not in self.revisions:
            row = self.conn.execute(
                """
                SELECT storage_key, source_sha256
                FROM chronicle.document_revisions WHERE revision_id = %s
                """,
                (revision_id,),
            ).fetchone()
            self.revisions[key] = (
                {"storage_key": row[0], "source_sha256": row[1]}
                if row is not None
                else None
            )
        return self.revisions[key]

    def member_origin(self, bundle: str) -> dict[str, Any] | None:
        """Resolve the exact (job, revision, storage, lookup) behind a bundle.

        Returns None when no worker output recorded the bundle (legacy
        fixtures stay ``unavailable`` instead of being guessed onto the
        reading review's job).
        """
        owner = self.owner_of(bundle)
        if owner is None:
            return None
        revision = self.revision_source(owner["revision_id"])
        if revision is None:
            return None
        return {
            "job_id": owner["job_id"],
            "revision_id": owner["revision_id"],
            "storage_key": revision["storage_key"],
            "source_sha256": revision["source_sha256"],
            "lookup": self.lookup_for(owner["job_id"]),
        }


def _chapter_lookup_cached(conn, *, job_id: Any) -> dict[str, Any]:
    # Loaded once per request and reused for every group/member in that
    # request (no cross-request staleness when later artifacts land).
    return _source_context.load_chapter_lookup(conn, job_id=job_id)


def _bundle_sha_and_title(
    conn, bundle: str, *, cache: dict[str, tuple[str | None, str | None]] | None = None
) -> tuple[str | None, str | None]:
    if cache is not None and bundle in cache:
        return cache[bundle]
    row = conn.execute(
        """
        SELECT bundle_payload, source_title
        FROM chronicle.source_bundles WHERE bundle_label = %s
        """,
        (bundle,),
    ).fetchone()
    if row is None:
        result = (None, None)
        if cache is not None:
            cache[bundle] = result
        return result
    from common import sha256_json as _sha256_json

    try:
        sha = _sha256_json(row[0]) if isinstance(row[0], dict) else None
    except Exception:
        sha = None
    result = (sha, row[1])
    if cache is not None:
        cache[bundle] = result
    return result


def _evidence_for_ref(
    conn, *, bundle: str, ref: str, link_kind: str, lookup: dict[str, Any]
) -> tuple[list[str], list[dict[str, Any]]]:
    kinds: list[str] = []

    def _add(kind: str) -> None:
        if kind not in kinds:
            kinds.append(kind)

    table = "chronicle.staged_entities" if link_kind == "entity" else "chronicle.staged_events"
    try:
        record_row = conn.execute(
            f"SELECT payload FROM {table} WHERE bundle_label = %s AND record_ref = %s",
            (bundle, ref),
        ).fetchone()
    except Exception:
        record_row = None
    record = record_row[0] if record_row is not None and isinstance(record_row[0], dict) else {}
    # Direct Claim evidence (exact record reference only, never title match).
    claim_rows = conn.execute(
        """
        SELECT record_ref, payload FROM chronicle.staged_claims
        WHERE bundle_label = %s ORDER BY record_ref
        """,
        (bundle,),
    ).fetchall()
    direct = _claim_evidence_from_rows(claim_rows, ref)
    if direct:
        _add("direct_claim")
    # Mention surfaces on the staged record or the chapter mention map.
    mentions = record.get("mentions") if isinstance(record, dict) else None
    if isinstance(mentions, list) and any(
        isinstance(item, dict) and isinstance(item.get("text"), str) for item in mentions
    ):
        _add("mention")
    anchors = (lookup.get("anchors_by_record") or {}).get(ref, [])
    by_ref = (lookup.get("by_ref") or {}).get(ref)
    if by_ref is not None:
        # Chapter mention/translation anchors also count as mention evidence.
        if anchors:
            _add("mention")
        _add("record_source")
    # Event participation: an entity named by an event that itself has
    # Claim evidence reads as event_context, never as direct_claim.
    if link_kind == "entity":
        try:
            event_rows = conn.execute(
                """
                SELECT payload FROM chronicle.staged_events
                WHERE bundle_label = %s
                """,
                (bundle,),
            ).fetchall()
        except Exception:
            event_rows = []
        for (event_payload,) in event_rows:
            if not isinstance(event_payload, dict):
                continue
            participants = [
                part.get("entity_ref")
                for part in (event_payload.get("participants") or [])
                if isinstance(part, dict)
            ]
            places = [
                place for place in (event_payload.get("places") or [])
                if isinstance(place, str)
            ]
            if ref in participants or ref in places:
                _add("event_context")
                break
    # Translation blocks referencing this record.
    if by_ref is not None and anchors:
        _add("translation")
    if not kinds:
        # No staged evidence at all: mandatory record_sources (or the
        # unavailable marker below) still give the reviewer something.
        _add("record_source")
    kinds.sort()
    return kinds, direct


def _describe_context(
    conn,
    identity: dict[str, Any],
    lookup: dict[str, Any],
    *,
    bundle: str,
    ref: str,
    bundle_cache: dict[str, tuple[str | None, str | None]] | None = None,
    request_cache: _SourceRequestCache | None = None,
) -> dict[str, Any]:
    payload = identity["payload"]
    link_kind = str(payload.get("link_kind") or "")
    bundle_sha, bundle_title = _bundle_sha_and_title(conn, bundle, cache=bundle_cache)
    if request_cache is not None:
        origin = request_cache.member_origin(bundle)
    else:  # pragma: no cover - compatibility path, callers pass a cache
        origin = None
    if origin is not None:
        lookup = origin["lookup"]
    chapter_info = (lookup.get("by_ref") or {}).get(ref, {}) if origin is not None else {}
    anchors = list((lookup.get("anchors_by_record") or {}).get(ref, [])) if origin is not None else []
    evidence_kinds, _direct = _evidence_for_ref(
        conn, bundle=bundle, ref=ref, link_kind=link_kind, lookup=lookup
    )
    if origin is None:
        available = False
        reason: str | None = "bundle_without_provenance"
    elif not anchors:
        available = False
        reason = (
            "no_chapter_anchor"
            if chapter_info
            else "legacy_fixture_without_location"
        )
    elif origin.get("storage_key") is None:
        available = False
        reason = "revision_without_storage"
    else:
        available = True
        reason = None
    anchor_summary = [
        {
            "anchor_id": item.get("anchor_id"),
            "chapter_id": item.get("chapter_id"),
            "start": item.get("start"),
            "end": item.get("end"),
            "quote_sha256": item.get("quote_sha256"),
        }
        for item in anchors[:10]
    ]
    return {
        "context_id": _source_context.context_id_for(
            str(identity["review_id"]), bundle, ref
        ),
        "bundle": bundle,
        "bundle_sha256": bundle_sha,
        "record_ref": ref,
        "link_kind": link_kind,
        "job_id": str(origin["job_id"]) if origin is not None else str(identity["job_id"]),
        "revision_id": str(origin["revision_id"])
        if origin is not None
        else str(identity["revision_id"]),
        "chapter_id": chapter_info.get("chapter_id"),
        "chapter_index": chapter_info.get("chapter_index"),
        "chapter_title": chapter_info.get("chapter_title"),
        "artifact_sha256": chapter_info.get("artifact_sha256"),
        "source_title": chapter_info.get("source_title") or bundle_title,
        "source_sha256": (origin.get("source_sha256") if origin is not None else None)
        or chapter_info.get("source_sha256")
        or identity.get("source_sha256"),
        "evidence_kinds": evidence_kinds,
        "available": available,
        "unavailable_reason": reason,
        "anchor_count": len(anchors),
        "anchors": anchor_summary,
    }


def _ordered_context_refs(
    payload: dict[str, Any], *, group_id: str | None
) -> tuple[list[dict[str, str]], str | None]:
    """Resolve the paged ref list for one contexts request.

    Returns (refs, resolved_group_id). Raises _BadRequest/_NotFound on
    scope errors so group cursors cannot be replayed elsewhere.
    """
    mode = payload.get("review_mode")
    if group_id is not None:
        group_refs = _source_context.group_member_refs(payload, group_id)
        if group_refs is None:
            raise _NotFound(f"unknown review group {group_id!r} for this review")
        return group_refs, group_id
    if mode == "chapter_pair" or not isinstance(payload.get("groups"), list) or not payload.get("groups"):
        return _source_context.frozen_member_refs(payload), None
    # Batch without a group filter: every frozen member, deduplicated.
    return _source_context.frozen_member_refs(payload), None


def _parse_context_list(query: dict[str, list[str]]) -> dict[str, Any]:
    allowed = frozenset({"group_id", "limit", "cursor"})
    unknown = sorted(set(query) - allowed)
    if unknown:
        raise _BadRequest(f"unsupported query parameters: {unknown}")
    group_id = _single(query, "group_id")
    try:
        limit = int(_single(query, "limit") or "50")
    except ValueError as exc:
        raise _BadRequest("limit must be an integer") from exc
    if not 1 <= limit <= 100:
        raise _BadRequest("limit must be within 1..100")
    cursor_raw = _single(query, "cursor")
    return {"group_id": group_id, "limit": limit, "cursor_raw": cursor_raw}


def _handle_contexts(
    conn,
    review_id: uuid.UUID,
    *,
    raw_query: str,
) -> tuple[int, str, bytes]:
    identity = _review_identity(conn, review_id)
    payload = identity["payload"]
    spec = _parse_context_list(parse_qs(raw_query, keep_blank_values=True))
    refs, resolved_group = _ordered_context_refs(payload, group_id=spec["group_id"])
    offset = 0
    if spec["cursor_raw"] is not None:
        try:
            offset = _source_context.decode_context_cursor(
                spec["cursor_raw"],
                review_id=str(review_id),
                group_id=resolved_group,
            )
        except _source_context.BadCursor as exc:
            raise _BadRequest(str(exc)) from exc
    if offset > len(refs):
        raise _BadRequest("context cursor is past the end of this group")
    request_cache = _SourceRequestCache(conn)
    lookup = _chapter_lookup_cached(conn, job_id=identity["job_id"])
    page_refs = refs[offset : offset + spec["limit"]]
    items = [
        _describe_context(
            conn, identity, lookup, bundle=item["bundle"], ref=item["ref"],
            bundle_cache=request_cache.bundles,
            request_cache=request_cache,
        )
        for item in page_refs
    ]
    next_offset = offset + len(page_refs)
    has_more = next_offset < len(refs)
    next_cursor = (
        _source_context.encode_context_cursor(
            review_id=str(review_id), group_id=resolved_group, offset=next_offset
        )
        if has_more
        else None
    )
    return 200, "application/json; charset=utf-8", _json_bytes(
        {
            "schema": "chronicle.review-source-contexts",
            "version": "0.1",
            "review_id": str(review_id),
            "group_id": resolved_group,
            "total": len(refs),
            "items": items,
            "has_more": has_more,
            "next_cursor": next_cursor,
        }
    )


def _handle_source(
    conn,
    review_id: uuid.UUID,
    anchor_id: str,
    *,
    raw_query: str,
    source_dir: Path | str | None,
) -> tuple[int, str, bytes]:
    query = parse_qs(raw_query, keep_blank_values=True)
    allowed = frozenset({"view", "cursor", "limit"})
    unknown = sorted(set(query) - allowed)
    if unknown:
        raise _BadRequest(f"unsupported query parameters: {unknown}")
    view = _single(query, "view") or "window"
    if view not in ("window", "chapter"):
        raise _BadRequest("view must be window|chapter")
    cursor_raw = _single(query, "cursor")
    limit_raw = _single(query, "limit")
    limit = _source_context.CHAPTER_PAGE_MAX
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except ValueError as exc:
            raise _BadRequest("limit must be an integer") from exc
        if view != "chapter":
            raise _BadRequest("limit is only supported for view=chapter")
        if not 1 <= limit <= _source_context.CHAPTER_PAGE_MAX:
            raise _BadRequest(
                f"limit must be within 1..{_source_context.CHAPTER_PAGE_MAX}"
            )
    identity = _review_identity(conn, review_id)
    payload = identity["payload"]
    frozen = {(item["bundle"], item["ref"]) for item in _source_context.frozen_member_refs(payload)}
    request_cache = _SourceRequestCache(conn)
    # Resolve the anchor through each frozen (bundle, ref) owner's exact
    # provenance: the bundle's worker output decides the owning job and
    # revision, and the anchor must be bound to that member's record in
    # the owner's chapter lookup. Bundle attribution is kept end to end,
    # so the same ref in another bundle can never authorize this anchor.
    candidates: list[dict[str, Any]] = []
    anchor_missing_everywhere = True
    for bundle, ref in sorted(frozen):
        origin = request_cache.member_origin(bundle)
        if origin is None:
            continue
        lookup = origin["lookup"]
        anchor = (lookup.get("anchors_by_id") or {}).get(anchor_id)
        if anchor is None or not isinstance(anchor, dict):
            continue
        anchor_missing_everywhere = False
        if ref not in set((lookup.get("anchor_records") or {}).get(anchor_id, [])):
            continue
        candidates.append({"bundle": bundle, "ref": ref, "origin": origin, "anchor": anchor})
    if not candidates:
        if anchor_missing_everywhere:
            raise _NotFound(f"unknown source anchor {anchor_id!r} for this review")
        raise _NotFound(f"source anchor {anchor_id!r} is not part of this review")
    # Deterministic pick when two jobs share one revision: frozen bundle order.
    match = sorted(candidates, key=lambda item: (item["bundle"], item["ref"]))[0]
    origin, anchor = match["origin"], match["anchor"]
    lookup = origin["lookup"]
    # Exact artifact/revision/hash match against the owning revision, never
    # the reading review's job: same text at another location or revision
    # is never substituted.
    if str(anchor.get("revision_id") or "") != str(origin["revision_id"]):
        raise _Conflict(
            "source_mismatch",
            "anchor revision does not match the owning revision; "
            "refusing to substitute another version",
        )
    expected_sha = str(origin.get("source_sha256") or "")
    if str(anchor.get("source_sha256") or "") != expected_sha:
        raise _Conflict(
            "source_mismatch",
            "anchor source hash does not match the owning revision",
        )
    storage_key = origin.get("storage_key")
    if not isinstance(storage_key, str) or not storage_key:
        raise _Conflict("source_unavailable", "revision source is not configured")
    try:
        text = _source_context.read_revision_text(source_dir, storage_key, expected_sha)
    except _source_context.SourceUnavailable as exc:
        raise _Conflict("source_unavailable", str(exc)) from exc
    except _source_context.SourceMismatch as exc:
        raise _Conflict("source_mismatch", str(exc)) from exc
    # Anchors are chapter-relative (chapter_plan.build_chapter_request):
    # re-base through the exact recorded chapter boundary and page only
    # that chapter.
    chapter_id = anchor.get("chapter_id")
    if not isinstance(chapter_id, str) or not chapter_id:
        raise _Conflict("source_unavailable", "anchor has no chapter binding")
    try:
        bounds = _source_context.chapter_bounds(lookup, chapter_id)
    except _source_context.SourceUnavailable as exc:
        raise _Conflict("source_unavailable", str(exc)) from exc
    chapter_start, chapter_end = bounds
    if not (0 <= chapter_start < chapter_end <= len(text)):
        raise _Conflict(
            "source_mismatch",
            "recorded chapter boundary is outside this revision text",
        )
    chapter_text = text[chapter_start:chapter_end]
    try:
        _source_context.verify_anchor_in_chapter(anchor, chapter_text)
    except _source_context.SourceMismatch as exc:
        raise _Conflict("source_mismatch", str(exc)) from exc
    anchor_start, anchor_end = int(anchor["start"]), int(anchor["end"])
    rev_start, rev_end = chapter_start + anchor_start, chapter_start + anchor_end
    if view == "window":
        if cursor_raw is not None:
            raise _BadRequest("cursor is only supported for view=chapter")
        window = _source_context.window_in_chapter(chapter_text, anchor_start, anchor_end)
        return 200, "application/json; charset=utf-8", _json_bytes(
            {
                "schema": "chronicle.review-source",
                "version": "0.1",
                "review_id": str(review_id),
                "anchor_id": anchor_id,
                "view": "window",
                "revision_id": str(origin["revision_id"]),
                "source_sha256": expected_sha,
                "chapter_id": chapter_id,
                "bundle": match["bundle"],
                "record_ref": match["ref"],
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
    if cursor_raw is not None:
        try:
            offset = _source_context.decode_source_cursor(
                cursor_raw, review_id=str(review_id), anchor_id=anchor_id, view=view
            )
        except _source_context.BadCursor as exc:
            raise _BadRequest(str(exc)) from exc
    if offset > len(chapter_text):
        raise _BadRequest("chapter cursor is past the end of this chapter")
    try:
        page = _source_context.chapter_page_for(
            chapter_text, offset, limit=limit, anchor=anchor
        )
    except _source_context.BadCursor as exc:
        raise _BadRequest(str(exc)) from exc
    next_cursor = (
        _source_context.encode_source_cursor(
            review_id=str(review_id),
            anchor_id=anchor_id,
            view=view,
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
            "revision_id": str(origin["revision_id"]),
            "source_sha256": expected_sha,
            "chapter_id": chapter_id,
            "bundle": match["bundle"],
            "record_ref": match["ref"],
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


def dispatch_reviews(
    conn,
    resolve_publish,
    *,
    method: str,
    path: str,
    raw_query: str = "",
    body: bytes = b"",
    source_dir: Path | str | None = None,
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
            source_dir=source_dir,
        )
    except _BadRequest as exc:
        return _error(400, "bad_request", str(exc))
    except _NotFound as exc:
        return _error(404, "not_found", str(exc))
    except _MethodNotAllowed as exc:
        return _error(405, "method_not_allowed", str(exc))
    except _Conflict as exc:
        return _error(409, exc.code, str(exc))
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


def _detail_with_sources(conn, review_id: uuid.UUID) -> dict[str, Any]:
    """Detail plus lightweight source/chapter descriptors and context entry.

    Only adds readable source/chapter provenance and the contexts entry;
    full chapter text is never inlined (one request caches
    (bundle_sha, ref) and the revision read via the lookup helpers).
    """
    item = _detail(conn, review_id)
    if item["scope"] in ("narrative", "person_state"):
        return item
    try:
        identity = _review_identity(conn, review_id)
    except _NotFound:
        return item
    request_cache = _SourceRequestCache(conn)
    lookup = _chapter_lookup_cached(conn, job_id=identity["job_id"])
    refs = _source_context.frozen_member_refs(
        identity["payload"] if isinstance(identity.get("payload"), dict) else {}
    )
    contexts: list[dict[str, Any]] = []
    for entry in refs:
        try:
            contexts.append(
                _describe_context(
                    conn, identity, lookup, bundle=entry["bundle"], ref=entry["ref"],
                    bundle_cache=request_cache.bundles,
                    request_cache=request_cache,
                )
            )
        except Exception:
            continue
    item["source_contexts"] = {
        "total": len(refs),
        "href": f"{STUDIO_REVIEWS_PREFIX}/{review_id}/contexts",
        "items": contexts,
    }
    item["source_entry"] = {
        "contexts_href": f"{STUDIO_REVIEWS_PREFIX}/{review_id}/contexts",
        "source_href_template": f"{STUDIO_REVIEWS_PREFIX}/{review_id}/sources/{{anchor_id}}",
        "revision_id": str(identity["revision_id"]),
        "source_sha256": identity.get("source_sha256"),
    }
    return item


def _scope_of(conn, review_id: uuid.UUID) -> str | None:
    row = conn.execute(
        "SELECT payload->>'scope' FROM chronicle.review_items WHERE review_id = %s",
        (review_id,),
    ).fetchone()
    return row[0] if row is not None else None


def _route(
    conn,
    resolve_publish,
    *,
    method: str,
    path: str,
    raw_query: str,
    body: bytes,
    source_dir: Path | str | None = None,
):
    query = parse_qs(raw_query, keep_blank_values=True)
    if path == STUDIO_REVIEWS_PREFIX:
        if method != "GET":
            raise _BadRequest(f"method {method} is not supported on {path}")
        spec = _parse_page(query)
        # Items, scope-wide open count and plan fingerprint all come from
        # this one read transaction, so a page never mixes snapshots.
        raw_rows = _review_rows(conn, spec=spec)
        has_more = len(raw_rows) > spec["limit"]
        page_rows = raw_rows[: spec["limit"]]
        fingerprint = _plan_fingerprint(conn, spec=spec)
        observed_at = datetime.now(timezone.utc).isoformat()
        items = [_summary(row, conn, plan_fingerprint=fingerprint) for row in page_rows]
        if has_more:
            last = page_rows[-1]
            next_cursor = _encode_cursor(
                review_scope=spec["review_scope"],
                status=spec["status"],
                job_id=spec["job_id"],
                link_kind=spec["link_kind"],
                created_at=last[6],
                review_id=last[0],
            )
        else:
            next_cursor = None
        return 200, "application/json; charset=utf-8", _json_bytes(
            {
                "schema": "chronicle.studio-review-page",
                "version": "0.2",
                "query": {
                    "status": spec["status"],
                    "job_id": str(spec["job_id"]) if spec["job_id"] is not None else None,
                    "link_kind": spec["link_kind"],
                    "review_scope": spec["review_scope"],
                    "limit": spec["limit"],
                },
                "items": items,
                "next_cursor": next_cursor,
                "open_count": _scope_open_count(conn, spec=spec),
                "observed_at": observed_at,
                "plan_fingerprint": fingerprint,
            }
        )

    prefix = STUDIO_REVIEWS_PREFIX + "/"
    if not path.startswith(prefix):
        raise _NotFound("route not found")
    parts = path[len(prefix):].split("/")
    if len(parts) == 1 and parts[0]:
        review_id = _require_uuid(parts[0], "review")
        if method != "GET":
            raise _BadRequest(f"method {method} is not supported on {path}")
        if _scope_of(conn, review_id) == "person_state":
            return _person_states().dispatch_person_state_review(
                conn, review_id, method=method, route="detail",
                raw_query=raw_query, source_dir=source_dir,
            )
        return 200, "application/json; charset=utf-8", _json_bytes(
            {"schema": "chronicle.review", "version": "0.1", "review": _detail_with_sources(conn, review_id)}
        )
    if len(parts) == 2 and parts[0] and parts[1] == "contexts":
        review_id = _require_uuid(parts[0], "review")
        if method != "GET":
            raise _MethodNotAllowed(f"method {method} is not supported on {path}")
        if _scope_of(conn, review_id) == "person_state":
            return _person_states().dispatch_person_state_review(
                conn, review_id, method=method, route="contexts",
                raw_query=raw_query, source_dir=source_dir,
            )
        return _handle_contexts(conn, review_id, raw_query=raw_query)
    if len(parts) == 3 and parts[0] and parts[1] == "sources" and parts[2]:
        review_id = _require_uuid(parts[0], "review")
        if method != "GET":
            raise _MethodNotAllowed(f"method {method} is not supported on {path}")
        if _scope_of(conn, review_id) == "person_state":
            return _person_states().dispatch_person_state_review(
                conn, review_id, method=method, route="sources",
                raw_query=raw_query, source_dir=source_dir, anchor_id=parts[2],
            )
        return _handle_source(
            conn, review_id, parts[2], raw_query=raw_query, source_dir=source_dir
        )
    if len(parts) == 2 and parts[0] and parts[1] == "decision":
        review_id = _require_uuid(parts[0], "review")
        if method != "POST":
            raise _BadRequest(f"method {method} is not supported on {path}")
        if _scope_of(conn, review_id) == "person_state":
            return _person_states().dispatch_person_state_review(
                conn, review_id, method=method, route="decision",
                raw_query=raw_query, body=body, source_dir=source_dir,
            )
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _BadRequest(f"request body must be a JSON object: {exc}") from exc
        if not isinstance(payload, dict):
            raise _BadRequest("request body must be a JSON object")
        import narrative_store
        if narrative_store.review_detail(conn, review_id) is not None:
            if set(payload) - {"decision", "rationale", "candidate_sha", "content", "reviewed_conclusion_ids"}:
                raise _BadRequest("unknown narrative decision field")
            narrative_store.decide(conn, review_id=review_id,
                candidate_sha=payload.get("candidate_sha"), decision=payload.get("decision"),
                rationale=payload.get("rationale"), content=payload.get("content"),
                reviewed_conclusion_ids=payload.get("reviewed_conclusion_ids"))
            return 200, "application/json; charset=utf-8", _json_bytes(
                {"schema": "chronicle.review", "version": "0.1", "review": _detail_with_sources(conn, review_id)})
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
            {"schema": "chronicle.review", "version": "0.1", "review": _detail_with_sources(conn, review_id)}
        )
    raise _NotFound("route not found")
