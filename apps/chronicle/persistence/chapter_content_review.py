"""Frozen, version-bound human exceptions for staged chapter production.

Uses the existing ingestion output log and stage_gate ReviewItems. This module
is the only writer of chapter-content decisions; HTTP and workers call it.
It does not grant identity or publication authority.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from psycopg.types.json import Jsonb

import chapter_contract
import control_plane
from common import PersistenceConflict, PersistenceError, sha256_json

REVIEW_SCOPE = "chapter_content"
REVIEW_MODE = "chapter_content"
OUTPUT_TYPE = "chapter-content-review"
PLAN_VERSION = "chapter-content-review-v1"
DECISIONS = ("accept", "revise", "reject")
ISSUE_TYPES = ("processing_error", "source_uncertainty")
DISPOSITIONS = ("resolved", "source_uncertainty", "rejected")


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise PersistenceError(f"{name} must be a SHA-256 string")
    return value


def _text(value: Any, name: str, maximum: int = 8000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise PersistenceError(f"{name} must be nonempty text up to {maximum} characters")
    return value.strip()


def _issues(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 2048:
        raise PersistenceError("issues must be an array of at most 2048 items")
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise PersistenceError("each issue must be an object")
        issue_id = _text(item.get("id"), "issue.id", 256)
        if issue_id in seen:
            raise PersistenceError("duplicate issue id")
        seen.add(issue_id)
        if item.get("type") not in ISSUE_TYPES:
            raise PersistenceError("issue.type must distinguish processing_error and source_uncertainty")
        _text(item.get("message"), "issue.message")
        if not isinstance(item.get("target"), (str, dict)) or "evidence" not in item:
            raise PersistenceError("each issue requires its target and evidence")
    return copy.deepcopy(value)


def build_review_packet(
    *, job_id, chunk_id, request, candidate, history, issues,
    validation_errors, pipeline_fingerprint, step_output_sha256s,
) -> dict[str, Any]:
    """Pure frozen packet builder. No model or persistence calls."""
    if not isinstance(request, dict):
        raise PersistenceError("content review requires the complete chapter request")
    for field in ("chapter_id", "revision_id", "normalized_text"):
        _text(request.get(field), f"request.{field}", 32768 if field == "normalized_text" else 256)
    if not isinstance(request.get("source_scope"), dict):
        raise PersistenceError("content review requires the program-owned source_scope")
    if candidate is not None and not isinstance(candidate, dict):
        raise PersistenceError("candidate must be an object or null")
    if not isinstance(history, list) or any(not isinstance(entry, dict) for entry in history):
        raise PersistenceError("history must retain the ordered list of model and correction records")
    if not isinstance(validation_errors, list) or any(not isinstance(error, str) for error in validation_errors):
        raise PersistenceError("validation_errors must be an array of strings")
    if not isinstance(step_output_sha256s, list):
        raise PersistenceError("step_output_sha256s must be an ordered array")
    for digest in step_output_sha256s:
        _sha(digest, "step output hash")
    packet = {
        "schema": "chronicle.chapter-content-review", "version": "0.1",
        "plan_version": PLAN_VERSION, "job_id": str(job_id), "chunk_id": str(chunk_id),
        "chapter_id": request["chapter_id"], "revision_id": str(request["revision_id"]),
        "request_fingerprint": chapter_contract.request_fingerprint(request),
        "candidate_sha256": sha256_json(candidate) if candidate is not None else None,
        "history_sha256": sha256_json(history),
        "pipeline_fingerprint": _sha(pipeline_fingerprint, "pipeline_fingerprint"),
        "step_output_sha256s": list(step_output_sha256s),
        "request": copy.deepcopy(request), "candidate": copy.deepcopy(candidate),
        "history": copy.deepcopy(history), "issues": _issues(issues),
        "validation_errors": list(validation_errors),
    }
    packet["plan_fingerprint"] = sha256_json(packet)
    return packet


def _header(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": REVIEW_SCOPE, "review_mode": REVIEW_MODE, "stage": "extract",
        "blocking": True,
        **{key: copy.deepcopy(packet[key]) for key in (
            "plan_version", "plan_fingerprint", "chapter_id", "request_fingerprint",
            "candidate_sha256", "history_sha256", "pipeline_fingerprint", "step_output_sha256s",
        )},
        "review_output_sha256": sha256_json(packet),
        "issue_count": len(packet["issues"]), "history_count": len(packet["history"]),
        "validation_errors": list(packet["validation_errors"]),
        "allowed_decisions": list(DECISIONS) if packet["candidate"] is not None else ["reject"],
    }


def freeze_content_review(
    conn, *, job_id, chunk_id, worker, request, candidate, history, issues,
    validation_errors, pipeline_fingerprint, step_output_sha256s,
) -> dict[str, Any]:
    """Persist/adopt one exact chapter packet under the worker's live lease.

    A new generation after a human revision gets a new item; a still-open
    generation is never silently replaced. All packet data is in the existing
    output log, so the gate is useful before an accepted chapter exists.
    """
    from resolve_publish import require_unexpired_lease

    packet = build_review_packet(
        job_id=job_id, chunk_id=chunk_id, request=request, candidate=candidate,
        history=history, issues=issues, validation_errors=validation_errors,
        pipeline_fingerprint=pipeline_fingerprint, step_output_sha256s=step_output_sha256s,
    )
    payload = _header(packet)
    with conn.transaction():
        require_unexpired_lease(conn, job_id=job_id, worker=worker)
        owner = conn.execute(
            "SELECT j.revision_id, j.status, c.job_id FROM chronicle.ingestion_jobs j"
            " JOIN chronicle.ingestion_chunks c ON c.chunk_id = %s WHERE j.job_id = %s",
            (chunk_id, job_id),
        ).fetchone()
        if owner is None or str(owner[0]) != str(request["revision_id"]) or owner[2] != job_id:
            raise PersistenceConflict("content review chapter/revision does not belong to this job")
        if owner[1] != "running":
            raise PersistenceConflict("content review can only be frozen by a running job")
        existing = conn.execute(
            "SELECT review_id, status, payload FROM chronicle.review_items"
            " WHERE job_id = %s AND chunk_id = %s AND payload->>'scope' = %s"
            " ORDER BY created_at, review_id",
            (job_id, chunk_id, REVIEW_SCOPE),
        ).fetchall()
        for review_id, status, previous in existing:
            if previous.get("plan_fingerprint") == packet["plan_fingerprint"]:
                loaded = read_content_review(conn, review_id)
                return {**loaded["payload"], "review_id": str(review_id), "status": status,
                        "decision": loaded["payload"].get("decision")}
            if status == "open":
                raise PersistenceConflict("plan_drift: an open chapter review binds a different version")
            if previous.get("request_fingerprint") != packet["request_fingerprint"] or previous.get("pipeline_fingerprint") != pipeline_fingerprint:
                raise PersistenceConflict("plan_drift: cannot change a chapter review's request or pipeline")
            if (previous.get("decision") or {}).get("decision") != "revise":
                raise PersistenceConflict("cannot replace a chapter version after its terminal content decision")
            old_history = read_content_review(conn, review_id)["packet"]["history"]
            if packet["history"][:len(old_history)] != old_history:
                raise PersistenceConflict("plan_drift: a revised chapter must retain the complete earlier history")
        for digest in set(step_output_sha256s):
            if conn.execute(
                "SELECT 1 FROM chronicle.ingestion_outputs WHERE job_id = %s AND revision_id = %s AND artifact_sha256 = %s",
                (job_id, owner[0], digest),
            ).fetchone() is None:
                raise PersistenceConflict("content review references a missing or foreign step output")
        control_plane.record_output_fenced(
            conn, job_id=job_id, revision_id=owner[0], worker=worker,
            artifact_type=OUTPUT_TYPE, artifact_sha256=payload["review_output_sha256"], payload=packet,
        )
        review_id = control_plane.open_review_item(
            conn, job_id=job_id, chunk_id=chunk_id, kind="stage_gate", payload=payload,
        )
        require_unexpired_lease(conn, job_id=job_id, worker=worker)
    return {**payload, "review_id": str(review_id), "status": "open", "decision": None}


def read_content_review(conn, review_id) -> dict[str, Any]:
    row = conn.execute(
        "SELECT ri.job_id, ri.chunk_id, ri.status, ri.payload, ri.created_at, ri.resolved_at,"
        " j.status, j.revision_id, r.source_sha256, r.storage_key, r.revision_no,"
        " r.filename, r.language, r.source_label, d.document_id, d.title"
        " FROM chronicle.review_items ri JOIN chronicle.ingestion_jobs j USING(job_id)"
        " JOIN chronicle.document_revisions r ON r.revision_id = j.revision_id"
        " JOIN chronicle.documents d ON d.document_id = r.document_id"
        " WHERE ri.review_id = %s AND ri.payload->>'scope' = %s",
        (review_id, REVIEW_SCOPE),
    ).fetchone()
    if row is None:
        raise PersistenceError(f"unknown chapter-content review {review_id}")
    payload = row[3]
    saved = conn.execute(
        "SELECT payload FROM chronicle.ingestion_outputs WHERE job_id = %s AND revision_id = %s"
        " AND artifact_type = %s AND artifact_sha256 = %s",
        (row[0], row[7], OUTPUT_TYPE, payload.get("review_output_sha256")),
    ).fetchone()
    if saved is None or not isinstance(saved[0], dict):
        raise PersistenceConflict("content review packet is unavailable")
    packet = saved[0]
    try:
        expected = build_review_packet(**{key: packet[key] for key in (
            "job_id", "chunk_id", "request", "candidate", "history", "issues",
            "validation_errors", "pipeline_fingerprint", "step_output_sha256s",
        )})
    except (KeyError, PersistenceError) as exc:
        raise PersistenceConflict("plan_drift: frozen chapter review packet is malformed") from exc
    if packet != expected or any(payload.get(key) != value for key, value in _header(packet).items()):
        raise PersistenceConflict("plan_drift: frozen chapter review data changed")
    if str(row[0]) != packet["job_id"] or str(row[1]) != packet["chunk_id"] or str(row[7]) != packet["revision_id"] or row[8] != packet["request"].get("source_sha256"):
        raise PersistenceConflict("plan_drift: chapter review provenance changed")
    return {
        "review_id": str(review_id), "job_id": row[0], "chunk_id": row[1],
        "status": row[2], "payload": copy.deepcopy(payload), "packet": copy.deepcopy(packet),
        "created_at": row[4], "resolved_at": row[5], "job_status": row[6],
        "revision_id": row[7], "storage_key": row[9],
        "document": {"document_id": str(row[14]), "title": row[15], "revision_no": row[10],
                     "filename": row[11], "language": row[12], "source_label": row[13], "source_sha256": row[8]},
    }


def validation_report(packet: dict[str, Any]) -> dict[str, Any]:
    if packet["candidate"] is None:
        return {"valid": False, "errors": ["尚未形成完整章节候选，不能接受部分产物"]}
    from staged_chapter_contract import validate_staged_candidate, flatten_staged_errors

    report = validate_staged_candidate(packet["request"], packet["candidate"])
    errors = list(dict.fromkeys([*packet["validation_errors"], *flatten_staged_errors(report)]))
    return {"valid": bool(report.get("valid")) and not errors, "errors": errors}


def normalize_content_decision(packet: dict[str, Any], decision: Any) -> dict[str, Any]:
    if not isinstance(decision, dict):
        raise PersistenceError("content decision must be an object")
    allowed = {"decision", "plan_fingerprint", "candidate_sha256", "history_sha256", "rationale", "issue_dispositions", "patches"}
    if set(decision) - allowed:
        raise PersistenceError("unknown chapter-content decision field")
    kind = decision.get("decision")
    if kind not in DECISIONS:
        raise PersistenceError("chapter-content decision must be accept, revise or reject")
    for field in ("plan_fingerprint", "candidate_sha256", "history_sha256"):
        if field not in decision:
            raise PersistenceError(f"{field} is required")
        if decision[field] != packet[field]:
            raise PersistenceConflict(f"plan_drift: {field} does not match the reviewed version")
    rationale = _text(decision.get("rationale"), "rationale", 4000)
    dispositions = decision.get("issue_dispositions")
    if not isinstance(dispositions, list):
        raise PersistenceError("every issue requires an explicit disposition")
    by_id = {item["id"]: item for item in packet["issues"]}
    seen: set[str] = set()
    clean: list[dict[str, Any]] = []
    for item in dispositions:
        if not isinstance(item, dict) or set(item) != {"issue_id", "disposition", "rationale"}:
            raise PersistenceError("invalid issue disposition")
        key = item["issue_id"]
        if not isinstance(key, str) or key not in by_id or key in seen:
            raise PersistenceError("issue dispositions contain an unknown or duplicate issue")
        seen.add(key)
        disposition = item["disposition"]
        if disposition not in DISPOSITIONS:
            raise PersistenceError("invalid issue disposition value")
        if disposition == "source_uncertainty" and by_id[key]["type"] != "source_uncertainty":
            raise PersistenceError("a processing error cannot be relabelled source uncertainty")
        clean.append({"issue_id": key, "disposition": disposition, "rationale": _text(item["rationale"], "issue rationale", 4000)})
    if seen != set(by_id):
        raise PersistenceError("every frozen issue must be addressed")
    result = {
        **{key: packet[key] for key in ("plan_fingerprint", "request_fingerprint", "candidate_sha256", "history_sha256", "pipeline_fingerprint")},
        "decision": kind, "rationale": rationale, "issue_dispositions": clean,
    }
    if kind == "revise":
        patches = decision.get("patches")
        if packet["candidate"] is None:
            raise PersistenceError("cannot patch a missing complete candidate; reject this production attempt")
        if not isinstance(patches, list) or not patches or len(patches) > 128:
            raise PersistenceError("revise requires 1..128 local patches")
        from chapter_production import apply_patches

        apply_patches(copy.deepcopy(packet["candidate"]), copy.deepcopy(patches))
        result["patches"] = copy.deepcopy(patches)
    else:
        if "patches" in decision:
            raise PersistenceError("accept/reject must not contain patches; a revision needs a new review")
        if kind == "accept":
            report = validation_report(packet)
            if not report["valid"]:
                raise PersistenceConflict("candidate_invalid: mechanical validation must pass before content acceptance")
    result["decision_sha256"] = sha256_json(result)
    return result


def resolve_content_review(conn, *, review_id, decision: dict[str, Any]) -> dict[str, Any]:
    """Serialize with cancellation/resume and commit decision + terminal status."""
    with conn.transaction():
        identity = conn.execute("SELECT job_id FROM chronicle.review_items WHERE review_id = %s", (review_id,)).fetchone()
        if identity is None:
            raise PersistenceError(f"unknown chapter-content review {review_id}")
        job = conn.execute("SELECT status FROM chronicle.ingestion_jobs WHERE job_id = %s FOR UPDATE", (identity[0],)).fetchone()
        conn.execute("SELECT review_id FROM chronicle.review_items WHERE review_id = %s FOR UPDATE", (review_id,))
        if job is None or job[0] not in ("running", "needs_review"):
            raise PersistenceConflict("cannot decide a cancelled or terminal chapter job")
        review = read_content_review(conn, review_id)
        if review["status"] != "open":
            raise PersistenceConflict("chapter review is already decided; reload the server result")
        fixed = normalize_content_decision(review["packet"], decision)
        conn.execute("UPDATE chronicle.review_items SET payload = payload || %s WHERE review_id = %s", (Jsonb({"decision": fixed}), review_id))
        control_plane.resolve_review_item(conn, review_id=review_id)
        if fixed["decision"] == "reject":
            control_plane.cancel_job(conn, job_id=identity[0])
    return fixed


def get_content_decision(conn, review_id) -> dict[str, Any] | None:
    """Read a committed decision with its frozen version bindings intact."""
    review = read_content_review(conn, review_id)
    if review["status"] == "open":
        return None
    fixed = review["payload"].get("decision")
    if review["status"] != "resolved" or not isinstance(fixed, dict):
        raise PersistenceConflict("chapter review has no valid content decision")
    unsigned = {key: value for key, value in fixed.items() if key != "decision_sha256"}
    if sha256_json(unsigned) != fixed.get("decision_sha256") or any(
        fixed.get(key) != review["packet"][key]
        for key in ("plan_fingerprint", "request_fingerprint", "candidate_sha256", "history_sha256", "pipeline_fingerprint")
    ):
        raise PersistenceConflict("plan_drift: recorded content decision changed")
    return copy.deepcopy(fixed)
