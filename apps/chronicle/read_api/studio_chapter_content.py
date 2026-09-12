"""Studio projection for staged chapter-content exceptions, before acceptance."""

from __future__ import annotations

import copy
import json
import math
import re
from typing import Any
from urllib.parse import parse_qs

import source_context as sources


def _store():
    import chapter_content_review
    return chapter_content_review


def _response(payload: dict[str, Any]) -> tuple[int, str, bytes]:
    return 200, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _params(raw_query: str, allowed: set[str]) -> dict[str, str]:
    from common import PersistenceError
    parsed = parse_qs(raw_query, keep_blank_values=True)
    if set(parsed) - allowed or any(len(values) != 1 for values in parsed.values()):
        raise PersistenceError("unknown or repeated chapter-content query parameter")
    return {key: value[0] for key, value in parsed.items()}


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    from common import PersistenceError
    try:
        result = int(value)
    except (ValueError, TypeError) as exc:
        raise PersistenceError(f"{name} must be an integer") from exc
    if isinstance(value, bool) or not minimum <= result <= maximum:
        raise PersistenceError(f"{name} must be within {minimum}..{maximum}")
    return result


def _anchor(review: dict[str, Any]) -> dict[str, Any]:
    import chapter_contract
    request = review["packet"]["request"]
    text = request["normalized_text"]
    quote_sha = sources.sha256_text(text)
    return {
        "anchor_id": chapter_contract.anchor_id_for(
            revision_id=str(review["revision_id"]), chapter_id=request["chapter_id"],
            start=0, end=len(text), quote_sha256=quote_sha,
        ),
        "chapter_id": request["chapter_id"], "start": 0, "end": len(text), "quote_sha256": quote_sha,
    }


def _descriptor(review: dict[str, Any]) -> dict[str, Any]:
    packet = review["packet"]
    anchor = _anchor(review)
    return {
        "context_id": sources.context_id_for(review["review_id"], "", anchor["anchor_id"]),
        "bundle": "", "bundle_sha256": None, "record_ref": anchor["anchor_id"],
        "link_kind": "chapter_content", "job_id": str(review["job_id"]),
        "revision_id": str(review["revision_id"]), "chapter_id": packet["chapter_id"],
        "chapter_index": None, "chapter_title": packet["request"].get("chapter_title") or packet["chapter_id"],
        "artifact_sha256": review["payload"]["review_output_sha256"],
        "source_title": review["document"]["title"], "source_sha256": review["document"]["source_sha256"],
        "evidence_kinds": ["record_source"], "available": bool(review["storage_key"]),
        "unavailable_reason": None if review["storage_key"] else "source_unavailable",
        "anchor_count": 1, "anchors": [anchor],
    }


def _history_label(entry: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            return str(value)[:160]
    return None


def _history_receipt(value: Any) -> dict[str, Any] | None:
    """Only transport observations belong in the protected review DTO."""
    if not isinstance(value, dict):
        return None
    safe = {}
    for key in ("requested_model", "model", "status", "incomplete_reason"):
        if key in value and (value[key] is None or isinstance(value[key], str)):
            safe[key] = value[key]
    for key in ("http_attempts", "http_status", "response_bytes", "elapsed_seconds"):
        item = value.get(key)
        if key in value and (item is None or (
            isinstance(item, (int, float)) and not isinstance(item, bool)
            and (not isinstance(item, float) or math.isfinite(item)) and item >= 0
        )):
            safe[key] = item
    if isinstance(value.get("injected_provider"), bool):
        safe["injected_provider"] = value["injected_provider"]
    if "usage" in value:
        usage = value["usage"]
        safe["usage"] = {
            key: usage[key] for key in ("input_tokens", "output_tokens", "total_tokens", "reasoning_tokens")
            if isinstance(usage, dict) and isinstance(usage.get(key), int)
            and not isinstance(usage[key], bool) and usage[key] >= 0
        } or None
    return safe


def _display_history_entries(conn, review, entries):
    """Rehydrate immutable model results without copying them into the packet.

    The model-facing history omits successful raw text to avoid repeating
    it in every prompt. Studio resolves that exact output, never the newest
    result for a step. One query serves the detail descriptor batch; a history
    page resolves only its selected entry.
    """
    from common import PersistenceConflict, sha256_json
    references = [entry["output_sha256"] for entry in entries if entry.get("output_sha256") is not None]
    if any(not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None for digest in references):
        raise PersistenceConflict("plan_drift: malformed frozen history output reference")
    refs = set(references)
    if refs - set(review["packet"]["step_output_sha256s"]):
        raise PersistenceConflict("plan_drift: history output is not in this review's frozen output set")
    outputs = {}
    if refs:
        rows = conn.execute(
            "SELECT artifact_sha256, artifact_type, payload FROM chronicle.ingestion_outputs"
            " WHERE job_id = %s AND revision_id = %s AND payload->>'chunk_id' = %s"
            " AND artifact_sha256 = ANY(%s)",
            (review["job_id"], review["revision_id"], str(review["chunk_id"]), sorted(refs)),
        ).fetchall()
        for digest, kind, payload in rows:
            if digest in outputs or kind not in (
                "chapter-production-attempt", "chapter-production-step", "chapter-production-draft",
            ) or not isinstance(payload, dict) or sha256_json(payload) != digest:
                raise PersistenceConflict("plan_drift: frozen history output is malformed or changed")
            if payload.get("chapter_id") != review["packet"]["chapter_id"] or payload.get("pipeline_fingerprint") != review["packet"]["pipeline_fingerprint"]:
                raise PersistenceConflict("plan_drift: frozen history output has different chapter provenance")
            outputs[digest] = (kind, payload)
        if set(outputs) != refs:
            raise PersistenceConflict("plan_drift: frozen history output is unavailable for this chapter")
    result = []
    hidden = {"prompt", "input", "request", "config", "model_config", "api_key", "api_key_env", "headers", "authorization"}
    for entry in entries:
        view = {key: copy.deepcopy(value) for key, value in entry.items() if key.lower().replace("-", "_") not in hidden}
        digest = entry.get("output_sha256")
        if digest is not None:
            kind, saved = outputs[digest]
            for key in ("step", "round", "slot", "model", "status", "parsed", "validation_errors",
                        "input_sha256", "parents", "decision", "candidate", "candidate_sha256", "parent_sha256", "raw_text", "receipt"):
                if key in entry and entry[key] != saved.get(key):
                    raise PersistenceConflict("plan_drift: frozen history projection differs from its stored output")
            if entry.get("artifact_type") not in (None, kind):
                raise PersistenceConflict("plan_drift: frozen history output type changed")
            for key in ("raw_text", "parsed", "receipt", "validation_errors", "error", "attempt"):
                if key in saved:
                    view[key] = copy.deepcopy(saved[key])
        if "receipt" in view:
            view["receipt"] = _history_receipt(view["receipt"])
        result.append(view)
    return result


def _patch_targets(candidate: Any) -> list[dict[str, Any]]:
    """Offer bounded object edits, with all patch authority in the producer."""
    from common import sha256_json
    if not isinstance(candidate, dict):
        return []
    targets: list[dict[str, Any]] = []
    def add(path, value, label):
        targets.append({"path": path, "before_sha256": sha256_json(value), "label": label})
    translation = candidate.get("translation")
    blocks = translation.get("blocks", []) if isinstance(translation, dict) else []
    for index, block in enumerate(blocks if isinstance(blocks, list) else []):
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            add(f"/translation/blocks/{index}/text", block["text"], f"第 {index + 1} 段译文")
    groups = [("/bundle/entities", "人物、地点及其他实体"), ("/bundle/events", "事件"),
              ("/bundle/claims", "事实"), ("/mentions", "称呼定位"), ("/record_sources", "来源关联"),
              ("/reading", "阅读关联"), ("/person_states", "人物阶段"), ("/warnings", "保留意见")]
    for root, label in groups:
        value = candidate
        for token in root[1:].split("/"):
            value = value.get(token) if isinstance(value, dict) else None
        if isinstance(value, dict):
            for field, group in value.items():
                path = root + "/" + field.replace("~", "~0").replace("/", "~1")
                if isinstance(group, list):
                    for index, entry in enumerate(group):
                        add(f"{path}/{index}", entry, f"{label} · {field} · {index + 1}")
                else:
                    add(path, group, f"{label} · {field}")
        elif isinstance(value, list):
            for index, entry in enumerate(value):
                name = (entry.get("canonical_name") or entry.get("name") or entry.get("temp_id")) if isinstance(entry, dict) else None
                add(f"{root}/{index}", entry, f"{label} · {name or index + 1}")
    return targets


def detail(conn, review_id) -> dict[str, Any]:
    from common import sha256_json
    review = _store().read_content_review(conn, review_id)
    packet = review["packet"]
    payload = review["payload"]
    report = _store().validation_report(packet)
    history = [
        {"index": index, "entry_sha256": sha256_json(entry),
         "step": _history_label(entry, "step", "kind", "stage"),
         "model": _history_label(entry, "model", "model_name"),
         "status": _history_label(entry, "status", "outcome")}
        for index, entry in enumerate(_display_history_entries(conn, review, packet["history"]))
    ]
    descriptor = _descriptor(review)
    open_count = conn.execute(
        "SELECT count(*) FROM chronicle.review_items WHERE job_id = %s AND status = 'open'", (review["job_id"],)
    ).fetchone()[0]
    decision = payload.get("decision")
    return {
        "review_id": str(review_id), "job_id": str(review["job_id"]), "chunk_id": str(review["chunk_id"]),
        "kind": "stage_gate", "status": review["status"], "job_status": review["job_status"],
        "created_at": review["created_at"].isoformat() if review["created_at"] else None,
        "resolved_at": review["resolved_at"].isoformat() if review["resolved_at"] else None,
        "revision_id": str(review["revision_id"]), "document": review["document"],
        "scope": "chapter_content", "review_mode": "chapter_content", "chapter_id": packet["chapter_id"],
        "plan_fingerprint": packet["plan_fingerprint"], "blocking": True, "link_kind": "",
        "allowed_decisions": payload["allowed_decisions"],
        "left_label": "章节内容审核", "right_label": None, "left": None, "right": None,
        "left_context": None, "right_context": None, "candidate_id": packet["chapter_id"],
        "resolution_sha256": None, "job_open_resolution_reviews": int(open_count),
        "suggestion": {"decision": None, "confidence": None, "signals": [], "rationale": None},
        "decision": ({"decision": decision["decision"], "rationale": decision["rationale"]} if decision else None),
        "source_contexts": {"total": 1, "href": f"/api/v1/studio/jobs/reviews/{review_id}/contexts", "items": [descriptor]},
        "chapter_content": {
            "schema": "chronicle.chapter-content-review", "version": "0.1",
            **{key: packet[key] for key in ("plan_fingerprint", "candidate_sha256", "history_sha256", "request_fingerprint", "pipeline_fingerprint", "step_output_sha256s")},
            "candidate": packet["candidate"], "issues": packet["issues"],
            "history": history, "history_count": len(history), "can_accept": report["valid"],
            "validation_errors": report["errors"], "source_scope": packet["request"]["source_scope"],
            "source": descriptor, "decision": decision, "patch_targets": _patch_targets(packet["candidate"]),
        },
    }


def history_page(conn, review_id, raw_query: str):
    """Page the full JSON of each history record without losing long results.

    Record descriptors stay light in detail; this endpoint includes the entire
    stored raw/parsed text across bounded pages, even if one record exceeds the
    Rust proxy response envelope. The cursor binds the exact plan and record.
    """
    from common import PersistenceError, sha256_json
    review = _store().read_content_review(conn, review_id)
    packet = review["packet"]
    params = _params(raw_query, {"entry", "cursor", "limit"})
    index = _integer(params.get("entry"), "entry", 0, max(0, len(packet["history"]) - 1))
    if not packet["history"]:
        raise PersistenceError("history has no records")
    entry = _display_history_entries(conn, review, [packet["history"][index]])[0]
    encoded = json.dumps(entry, ensure_ascii=False, sort_keys=True, indent=2)
    key = f"{packet['plan_fingerprint']}:{index}:{sha256_json(entry)}"
    cursor = params.get("cursor")
    offset = sources.decode_context_cursor(cursor, review_id=str(review_id), group_id=key) if cursor else 0
    if offset > len(encoded):
        raise PersistenceError("history cursor is outside this record")
    limit = _integer(params.get("limit", 16000), "limit", 1, 16000)
    end = min(len(encoded), offset + limit)
    return _response({
        "schema": "chronicle.chapter-review-history", "version": "0.1", "review_id": str(review_id),
        "plan_fingerprint": packet["plan_fingerprint"], "entry": index, "entry_sha256": sha256_json(entry),
        "text": encoded[offset:end], "has_more": end < len(encoded),
        "next_cursor": sources.encode_context_cursor(review_id=str(review_id), group_id=key, offset=end) if end < len(encoded) else None,
    })


def source(conn, review_id, anchor_id: str, raw_query: str, source_dir):
    from common import PersistenceError
    review = _store().read_content_review(conn, review_id)
    request = review["packet"]["request"]
    anchor = _anchor(review)
    if anchor_id != anchor["anchor_id"]:
        raise PersistenceError(f"unknown source anchor {anchor_id} for this review")
    params = _params(raw_query, {"view", "cursor", "limit"})
    view = params.get("view", "window")
    if view not in ("window", "chapter") or (view == "window" and ("cursor" in params or "limit" in params)):
        raise PersistenceError("source view must be window or chapter; pagination belongs to chapter")
    full_text = sources.read_revision_text(source_dir, review["storage_key"], review["document"]["source_sha256"])
    if sources.sha256_text(full_text) != request.get("revision_normalized_sha256"):
        raise sources.SourceMismatch("normalized revision hash differs from this frozen request")
    start, end = request.get("chapter_start"), request.get("chapter_end")
    if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool) or not 0 <= start < end <= len(full_text):
        raise sources.SourceMismatch("frozen chapter bounds are invalid")
    chapter_text = full_text[start:end]
    if chapter_text != request["normalized_text"] or sources.sha256_text(chapter_text) != request.get("normalized_sha256"):
        raise sources.SourceMismatch("frozen chapter text no longer matches its revision range")
    sources.verify_anchor_in_chapter(anchor, chapter_text)
    offset = 0
    if params.get("cursor"):
        offset = sources.decode_source_cursor(params["cursor"], review_id=str(review_id), anchor_id=anchor_id, view=view)
    if view == "chapter":
        limit = _integer(params.get("limit", 16000), "limit", 1, 16000)
        page = sources.chapter_page_for(chapter_text, offset, limit=limit, anchor=anchor)
    else:
        # The descriptor represents the complete chapter. A window remains a
        # preview; the chapter route always exposes every code point.
        page = sources.window_in_chapter(chapter_text, 0, min(400, len(chapter_text)))
        page["has_more"] = False
    cursor = sources.encode_source_cursor(review_id=str(review_id), anchor_id=anchor_id, view=view, offset=page["slice_end"]) if page["has_more"] else None
    return _response({
        "schema": "chronicle.review-source", "version": "0.1", "review_id": str(review_id), "anchor_id": anchor_id,
        "view": view, "revision_id": str(review["revision_id"]), "source_sha256": review["document"]["source_sha256"],
        "chapter_id": request["chapter_id"], "bundle": "", "record_ref": anchor_id,
        "bounds": {"start": start, "end": end, "slice_start": start + page["slice_start"],
                   "slice_end": start + page["slice_end"], "chapter_start": start, "chapter_end": end, "chapter_length": len(chapter_text)},
        "source_hash": sources.sha256_text(full_text), "chapter_hash": sources.sha256_text(chapter_text),
        "text": page["text"], "segments": page["segments"], "has_more": page["has_more"], "next_cursor": cursor,
    })


def dispatch(conn, review_id, *, method, route, raw_query="", body=b"", source_dir=None, anchor_id=None):
    from common import PersistenceError, PersistenceConflict
    # Reuse the envelope/error translation of the owning review router.
    try:
        if route == "detail" and method == "GET":
            _params(raw_query, set())
            return _response({"schema": "chronicle.review", "version": "0.1", "review": detail(conn, review_id)})
        if route == "contexts" and method == "GET":
            params = _params(raw_query, {"limit", "cursor"})
            if "limit" in params:
                _integer(params["limit"], "limit", 1, 100)
            if params.get("cursor"):
                raise PersistenceError("chapter source has only one context")
            review = _store().read_content_review(conn, review_id)
            return _response({"schema": "chronicle.review-source-contexts", "version": "0.1", "review_id": str(review_id),
                              "group_id": None, "total": 1, "items": [_descriptor(review)], "has_more": False, "next_cursor": None})
        if route == "history" and method == "GET":
            return history_page(conn, review_id, raw_query)
        if route == "sources" and method == "GET":
            return source(conn, review_id, anchor_id, raw_query, source_dir)
        if route == "decision" and method == "POST":
            _params(raw_query, set())
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PersistenceError("chapter-content decision must be JSON") from exc
            _store().resolve_content_review(conn, review_id=review_id, decision=payload)
            return _response({"schema": "chronicle.review", "version": "0.1", "review": detail(conn, review_id)})
        raise PersistenceError("unsupported chapter-content route or method")
    except PersistenceConflict as exc:
        from studio_reviews import _Conflict
        code = "plan_drift" if str(exc).startswith("plan_drift:") else "candidate_invalid" if str(exc).startswith("candidate_invalid:") else "conflict"
        raise _Conflict(code, str(exc)) from exc
    except sources.BadCursor as exc:
        raise PersistenceError(str(exc)) from exc
    except (sources.SourceUnavailable, sources.SourceMismatch) as exc:
        from studio_reviews import _Conflict
        code = "source_unavailable" if isinstance(exc, sources.SourceUnavailable) else "source_mismatch"
        raise _Conflict(code, str(exc)) from exc
