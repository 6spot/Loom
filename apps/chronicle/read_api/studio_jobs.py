"""Studio ingestion-job endpoints for the Chronicle internal sidecar.

These routes live behind the Rust ``chronicle-server`` Studio namespace,
which enforces the single-administrator authentication boundary (C1-T2).
The sidecar itself is never published outside the deployment network; the
Rust proxy authenticates first and forwards only method/path/query/body.

Lifecycle authority stays in the control plane: every state change goes
through ``apps/chronicle/persistence/control_plane.py`` (whose state
machine mirrors the normative Rust ``apps/chronicle/control_plane``
contract), so queue/inspect/retry/resume/cancel can never invent a
transition the contract forbids.

Studio deliberately exposes a *safe projection* of job detail. The underlying
staged worker checkpoints are replay/audit records and may contain
verbatim prompts, raw model responses, candidates and context. Those bytes
remain durable in PostgreSQL but are not a browser API. Studio receives
version/hash/validation/error metadata for progress. Explicit output reads
provide paginated saved model content through a positive field projection;
prompts, inputs, transport configuration and credentials stay server-side.

All responses are JSON under a ``chronicle.*`` schema:

```text
POST   /api/v1/studio/jobs                        {"revision_id": "..."}
GET    /api/v1/studio/jobs[?status=&limit=&offset=]
GET    /api/v1/studio/jobs/{job_id}
POST   /api/v1/studio/jobs/{job_id}/retry
POST   /api/v1/studio/jobs/{job_id}/resume
POST   /api/v1/studio/jobs/{job_id}/cancel
GET    /api/v1/studio/jobs/model-options
GET    /api/v1/studio/jobs/history/model-options
POST   /api/v1/studio/jobs/{job_id}/rerun
POST   /api/v1/studio/jobs/{job_id}/new-run
GET    /api/v1/studio/jobs/{job_id}/outputs/{sha}[?offset=&limit=]
```
"""

from __future__ import annotations

import copy
import json
import os
import re
import uuid
from typing import Any
from urllib.parse import parse_qs

STUDIO_JOBS_PREFIX = "/api/v1/studio/jobs"

_JOB_ACTIONS = ("retry", "resume", "cancel")
_JOB_ACTION_LABELS = {
    "retry": "重试",
    "resume": "继续生产",
    "cancel": "取消任务",
    "new_run": "新建运行",
}
_REVIEW_SCOPE_LABELS = {
    "resolution": "来源关系审核",
    "narrative": "综合史料审核",
    "chapter_content": "章节内容审核",
    "person_state": "阶段依据审核",
}


def _error(status: int, code: str, message: str) -> tuple[int, str, bytes]:
    payload = {
        "schema": "chronicle.error",
        "version": "0.1",
        "error": {"code": code, "message": _safe_error(message)},
    }
    return status, "application/json; charset=utf-8", _json_bytes(payload)


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _single(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if not values:
        return None
    if len(values) != 1:
        raise _BadRequest(f"query parameter {name} must appear once")
    return values[0]


class _BadRequest(Exception):
    pass


class _NotFound(Exception):
    pass


def _require_uuid(value: str, description: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise _NotFound(f"{description} {value!r} is not a valid UUID") from exc


def _safe_validation(value: Any) -> Any:
    """Copy deterministic validation metadata, excluding unknown rich values.

    Validator reports are expected to be JSON objects/lists/scalars and do
    not contain credentials. Keeping the shape is useful in Studio because a
    failed extraction should explain *why* it failed without returning the
    model prompt/response that produced the report.
    """
    if isinstance(value, str):
        return _safe_error(value)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, list):
        return [_safe_validation(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _safe_validation(item)
            for key, item in value.items()
            if not _private_key(key)
        }
    return str(value)


def _private_key(key: Any) -> bool:
    normalized = str(key).lower().replace("-", "_")
    if normalized in {"token", "input"}:
        return True
    return any(part in normalized for part in (
        "api_key", "apikey", "authorization", "password", "secret", "credential",
        "access_token", "refresh_token", "private_key", "model_config", "transport",
        "endpoint", "url", "server_path", "storage_path", "storage_key", "filesystem_path", "path",
        "headers", "prompt",
    ))


def _safe_browser_value(value: Any) -> Any:
    """Recursively redact secret-shaped nested fields at the API boundary."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_safe_browser_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _safe_browser_value(item)
            for key, item in value.items()
            if not _private_key(key)
        }
    return str(value)


def _safe_document(value: Any) -> dict[str, Any]:
    """Project the small immutable-source descriptor used by Studio."""
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key in (
        "document_id", "title", "filename", "source_sha256", "language", "source_label",
    ):
        item = value.get(key)
        if isinstance(item, str):
            result[key] = item
    revision_no = value.get("revision_no")
    if isinstance(revision_no, int) and not isinstance(revision_no, bool):
        result["revision_no"] = revision_no
    return result


def _safe_error(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    # Error text is useful operator metadata, but provider exceptions must
    # not turn an accidental key/path into an API response.
    value = re.sub(
        r"(?i)(api[_-]?key|authorization|bearer|password|secret|token)\s*[:=]\s*[^\s,;]+",
        "[已脱敏]",
        value,
    )
    value = re.sub(
        r"(?i)(endpoint|url|server[_-]?path|storage[_-]?path)\s*[:=]\s*[^\s,;]+",
        "[已脱敏]",
        value,
    )
    value = re.sub(r"https?://[^\s,;]+", "[已脱敏]", value)
    return re.sub(r"(?<![\w])/(?:home|srv|var|etc|tmp|opt)/[^\s,;]+", "[已脱敏]", value)


def _safe_run_checkpoint(checkpoint: Any) -> dict[str, Any]:
    """Project a replay checkpoint into browser-safe debugging metadata.

    Explicitly omitted, even when present:
    ``prompt``, ``raw_response``, ``candidate``, full request/context payloads,
    and any unrecognized keys. Hashes and deterministic validation reports are
    enough to correlate a Studio failure with the durable server-side run.
    """
    if not isinstance(checkpoint, dict):
        return {}
    projected: dict[str, Any] = {}
    for key in (
        "extraction_version",
        "contract_version",
        "prompt_version",
        "model_version",
        "attempt_count",
        "accepted",
        "error",
        "authoritative",
        "authority_note",
    ):
        value = checkpoint.get(key)
        if value is None or isinstance(value, (str, int, float, bool)):
            if value is not None:
                projected[key] = _safe_error(value) if key in ("error", "authority_note") else value

    attempts = checkpoint.get("attempts")
    if isinstance(attempts, list):
        safe_attempts: list[dict[str, Any]] = []
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            safe_attempt: dict[str, Any] = {}
            for key in (
                "kind",
                "prompt_sha256",
                "raw_response_sha256",
                "parse_error",
            ):
                value = attempt.get(key)
                if value is None or isinstance(value, (str, int, float, bool)):
                    if value is not None:
                        safe_attempt[key] = _safe_error(value) if key == "parse_error" else value
            if "validation" in attempt:
                safe_attempt["validation"] = _safe_validation(attempt.get("validation"))
            safe_attempts.append(safe_attempt)
        projected["attempts"] = safe_attempts
    return projected


def _safe_production(value: Any) -> dict[str, Any]:
    """Expose progress; saved content is read on demand from output/review routes."""
    if not isinstance(value, dict):
        return {}
    result = {key: value[key] for key in ("step", "status", "model", "pipeline_fingerprint")
              if isinstance(value.get(key), str)}
    steps = value.get("steps")
    result["steps"] = []
    if isinstance(steps, dict):
        for entry in steps.values():
            if not isinstance(entry, dict):
                continue
            safe = {key: entry[key] for key in ("step", "slot", "model", "status", "output_sha256")
                    if isinstance(entry.get(key), str)}
            if "error" in entry:
                safe["error"] = _safe_error(entry.get("error"))
            for key in ("round", "attempt", "elapsed_seconds"):
                number = entry.get(key)
                if isinstance(number, (int, float)) and not isinstance(number, bool) and number >= 0:
                    safe[key] = number
            usage = entry.get("usage")
            safe["usage"] = ({key: usage[key] for key in (
                "input_tokens", "output_tokens", "total_tokens", "reasoning_tokens")
                if isinstance(usage.get(key), int) and not isinstance(usage[key], bool) and usage[key] >= 0}
                if isinstance(usage, dict) else None)
            result["steps"].append(safe)
    return result


def _studio_job_projection(detail: dict[str, Any]) -> dict[str, Any]:
    """Return the unified, browser-safe C3-T07 job projection.

    ``detail`` is the unrestricted control-plane read. This function is the
    single positive projection used by both chapter production and history
    jobs; in particular, it never copies the job/stage/chunk checkpoints.
    """
    try:
        import control_plane
        import studio_production
    except ModuleNotFoundError:
        # The projection unit tests intentionally load this read module
        # without the persistence package on sys.path. Keep the pure shape
        # test importable while production requests use the real modules.
        class _ProjectionDefinitions:
            TASK_LABELS = {"chapter": "章节生产任务", "narrative": "多史料综合任务"}
            STAGE_LABELS = {
                "prepare": "准备", "structure": "结构识别", "segment": "分段",
                "extract": "内容抽取", "assemble": "组装草稿", "resolve": "来源核对",
                "publish": "发布", "present": "综合呈现",
            }
            STAGE_DEPENDENCIES = {
                "prepare": (), "structure": ("prepare",), "segment": ("structure",),
                "extract": ("segment",), "assemble": ("extract",), "resolve": ("assemble",),
                "publish": ("resolve",), "present": ("publish",),
            }

        class _ProjectionControlPlane:
            STAGE_NAMES = tuple(_ProjectionDefinitions.STAGE_LABELS)

            @staticmethod
            def action_state_from_values(**values):
                status = values.get("status", "queued")
                attempt = int(values.get("attempt", 0))
                maximum = int(values.get("max_attempts", 1))
                open_reviews = int(values.get("open_reviews", 0))
                rows = [
                    ("retry", status == "failed" and attempt < maximum,
                     None if status == "failed" and attempt < maximum else "仅失败任务可以重试"),
                    ("resume", status == "needs_review" and open_reviews == 0,
                     None if status == "needs_review" and open_reviews == 0 else "仅待审核任务可以继续"),
                    ("cancel", status in ("queued", "running", "needs_review"),
                     None if status in ("queued", "running", "needs_review") else "终态任务不能取消"),
                    ("new_run", status in ("failed", "cancelled"),
                     None if status in ("failed", "cancelled") else "仅失败或已取消任务可以新建运行"),
                ]
                actions = [{"key": key, "available": available, "enabled": available, "reason": reason}
                           for key, available, reason in rows]
                return {
                    "actions": actions,
                    "available_actions": [key for key, available, _reason in rows if available],
                    "action_reasons": {key: reason for key, _available, reason in rows if reason},
                }

        studio_production = _ProjectionDefinitions
        control_plane = _ProjectionControlPlane

    document = _safe_document(detail.get("document"))
    kind = detail.get("job_kind") if detail.get("job_kind") in studio_production.TASK_LABELS else "chapter"
    title = detail.get("title") if isinstance(detail.get("title"), str) else None
    title = title or document.get("title") or "未命名任务"
    source_count = detail.get("source_count") if isinstance(detail.get("source_count"), int) else 1
    task = {
        "type": kind,
        "machine_key": kind,
        "label": studio_production.TASK_LABELS[kind],
        "title": title,
        "source_count": source_count,
    }
    result = {
        key: copy.deepcopy(detail.get(key))
        for key in (
            "job_id",
            "revision_id",
            "status",
            "attempt",
            "max_attempts",
            "lease_owner",
            "lease_expires_at",
            "error",
            "created_at",
            "updated_at",
            "open_reviews",
            "document",
            "job_kind",
            "source_count",
            "current_stage",
            "production_request",
            "narrative_acceptances",
        )
    }
    result["document"] = document
    result["production_request"] = (
        _safe_browser_value(detail.get("production_request"))
        if isinstance(detail.get("production_request"), dict) else None
    )
    result["narrative_acceptances"] = (
        _safe_browser_value(detail.get("narrative_acceptances"))
        if isinstance(detail.get("narrative_acceptances"), list) else []
    )
    result["job_kind"] = kind
    result["job_kind_label"] = studio_production.TASK_LABELS[kind]
    result["title"] = title
    result["task"] = task
    result["source"] = _safe_browser_value(detail.get("source")) if detail.get("source") else {
        "revision_id": detail.get("revision_id"),
        "document_id": document.get("document_id"),
        "revision_no": document.get("revision_no"),
        "source_count": source_count,
        "relationship": "immutable_revision",
    }
    result["error"] = _safe_error(result.get("error"))

    raw_stages = [stage for stage in detail.get("stages", []) if isinstance(stage, dict)]
    stage_statuses = {
        stage.get("stage"): stage.get("status")
        for stage in raw_stages
        if isinstance(stage.get("stage"), str)
    }
    current_stage = detail.get("current_stage")
    order = {name: index for index, name in enumerate(control_plane.STAGE_NAMES)}
    if current_stage not in stage_statuses:
        candidates = [
            stage.get("stage") for stage in raw_stages
            if stage.get("status") in ("running", "needs_review", "failed")
        ]
        if not candidates:
            candidates = [stage.get("stage") for stage in raw_stages if stage.get("status") == "pending"]
        if not candidates:
            candidates = [stage.get("stage") for stage in raw_stages]
        candidates = [item for item in candidates if isinstance(item, str)]
        if candidates:
            terminal_only = all(
                stage.get("status") in ("completed", "skipped")
                for stage in raw_stages
                if isinstance(stage.get("stage"), str)
            )
            current_stage = (
                max(candidates, key=lambda value: order.get(value, -1))
                if terminal_only
                else min(candidates, key=lambda value: order.get(value, len(order)))
            )
    stage_projection = []
    for stage in raw_stages:
        key = stage.get("stage")
        if not isinstance(key, str):
            continue
        status = stage.get("status")
        dependencies = list(studio_production.STAGE_DEPENDENCIES.get(key, ()))
        dependency_statuses = [stage_statuses.get(dep) for dep in dependencies]
        blocked_reason = None
        if status == "pending" and any(dep in ("failed", "needs_review") for dep in dependency_statuses):
            blocked_reason = "前置步骤未完成"
        elif status == "pending" and any(dep not in ("completed", "skipped") for dep in dependency_statuses):
            blocked_reason = "等待前置步骤"
        stage_projection.append({
            "key": key,
            "machine_key": key,
            "stage": key,
            "label": studio_production.STAGE_LABELS.get(key, "步骤"),
            "status": status,
            "attempt": stage.get("attempt"),
            "dependencies": dependencies,
            "failure_reason": _safe_error(stage.get("error")),
            "blocked_reason": blocked_reason,
            "started_at": stage.get("started_at"),
            "finished_at": stage.get("finished_at"),
        })
    stage_projection.sort(
        key=lambda stage: order.get(stage["key"], len(order))
    )
    result["current_stage"] = current_stage
    result["current_step"] = next(
        (
            {
                "key": item["key"],
                "machine_key": item["machine_key"],
                "label": item["label"],
                "status": item["status"],
                "failure_reason": item["failure_reason"],
            }
            for item in stage_projection
            if item["key"] == current_stage
        ),
        None,
    )
    result["current_step_key"] = current_stage
    result["current_step_label"] = (
        studio_production.STAGE_LABELS.get(current_stage) if current_stage else None
    )
    result["stages"] = stage_projection
    result["steps"] = copy.deepcopy(stage_projection)
    result["step_graph"] = {
        "current_step": current_stage,
        "steps": copy.deepcopy(stage_projection),
        "dependencies": {
            item["key"]: list(item["dependencies"]) for item in stage_projection
        },
    }

    state = detail.get("action_state")
    if not isinstance(state, dict):
        try:
            state = control_plane.action_state_from_values(
                job_id=detail.get("job_id", ""), status=detail.get("status", "queued"),
                attempt=int(detail.get("attempt") or 0),
                max_attempts=int(detail.get("max_attempts") or 1),
                open_reviews=int(detail.get("open_reviews") or 0),
                narrative_scope=detail.get("narrative_scope") if kind == "narrative" else None,
            )
        except Exception:
            state = {"actions": [], "available_actions": [], "action_reasons": {}}
    authoritative_actions = state.get("actions") if isinstance(state, dict) else None
    if isinstance(authoritative_actions, list) and authoritative_actions:
        action_rows = []
        paths = {"new_run": "new-run"}
        for item in authoritative_actions:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            if not isinstance(key, str):
                continue
            action_rows.append({
                **item,
                "label": _JOB_ACTION_LABELS.get(key, "任务操作"),
                "method": "POST",
                "href": f"{STUDIO_JOBS_PREFIX}/{detail.get('job_id')}/{paths.get(key, key)}",
            })
        actions = action_rows
    else:
        # Legacy callers may provide only the already-computed action rows.
        # Production requests always carry the authoritative control-plane
        # state above; this fallback keeps old fixtures readable.
        actions = detail.get("actions") if isinstance(detail.get("actions"), list) else []
    result["action_state"] = _safe_browser_value(state)
    result["actions"] = _safe_browser_value(actions)
    result["available_actions"] = list(
        state.get("available_actions") or [item.get("key") for item in actions if item.get("available")]
    )
    result["action_reasons"] = _safe_browser_value(state.get("action_reasons") or {
        item.get("key"): item.get("reason") for item in actions if item.get("reason")
    })

    result["chunks"] = []
    for chunk in detail.get("chunks", []):
        if not isinstance(chunk, dict):
            continue
        projected_chunk = {
            key: copy.deepcopy(chunk.get(key))
            for key in (
                "chunk_id",
                "title",
                "section_id",
                "chunk_index",
                "status",
                "attempt",
                "max_attempts",
                "source_start",
                "source_end",
                "source_sha256",
                "content_sha256",
            )
        }
        projected_chunk["runs"] = [
            {
                "run_id": run.get("run_id"),
                "attempt": run.get("attempt"),
                "status": run.get("status"),
                "worker": run.get("worker"),
                "error": _safe_error(run.get("error")),
                "started_at": run.get("started_at"),
                "finished_at": run.get("finished_at"),
                "meta": _safe_run_checkpoint(run.get("checkpoint")),
            }
            for run in chunk.get("runs", [])
            if isinstance(run, dict)
        ]
        checkpoint = chunk.get("checkpoint")
        if isinstance(checkpoint, dict):
            production = _safe_production(checkpoint.get("production"))
            if production:
                projected_chunk["production"] = production
        result["chunks"].append(projected_chunk)
    # T10 needs review debt/progress visibility but does not own the review
    # decision payload; C1-T11 will expose its own purpose-built review API.
    result["reviews"] = [
        {
            "review_id": review.get("review_id"),
            "kind": review.get("kind"),
            "status": review.get("status"),
            "chunk_id": review.get("chunk_id"),
            "created_at": review.get("created_at"),
            "resolved_at": review.get("resolved_at"),
            "scope": (review.get("payload") or {}).get("scope"),
            "scope_label": _REVIEW_SCOPE_LABELS.get((review.get("payload") or {}).get("scope"), "审核"),
            "narrative_kind": (review.get("payload") or {}).get("kind"),
        }
        for review in detail.get("reviews", [])
        if isinstance(review, dict)
    ]
    result["outputs"] = []
    for output in detail.get("outputs", []):
        if not isinstance(output, dict):
            continue
        projected = {
            "output_id": output.get("output_id"),
            "artifact_type": output.get("artifact_type"),
            "artifact_sha256": output.get("artifact_sha256"),
            "revision_id": result.get("revision_id"),
            "created_at": output.get("created_at"),
            **{
                key: output[key]
                for key in (
                    "step", "model", "status", "chunk_id", "attempt", "round", "slot", "readable",
                    "acceptance_links",
                )
                if key in output
            },
        }
        if projected.get("readable") and projected.get("artifact_sha256") and result.get("job_id"):
            projected["href"] = (
                f"{STUDIO_JOBS_PREFIX}/{result['job_id']}/outputs/{projected['artifact_sha256']}"
            )
        result["outputs"].append(_safe_browser_value(projected))
    result["attempts"] = []
    for attempt in detail.get("attempts", []):
        if not isinstance(attempt, dict):
            continue
        projected_attempt = _safe_browser_value(attempt)
        step = projected_attempt.get("step")
        projected_attempt["step_label"] = studio_production.STAGE_LABELS.get(step, "模型步骤")
        if (
            projected_attempt.get("comparison_status") == "agreed"
            and (
                projected_attempt.get("status") != "completed"
                or not projected_attempt.get("output_complete")
                or projected_attempt.get("validation_status") == "failed"
            )
        ):
            projected_attempt["comparison_status"] = "unavailable"
        result_sha = projected_attempt.get("result_sha256") or projected_attempt.get("output_sha256")
        if result_sha and result.get("job_id"):
            projected_attempt["result_href"] = f"{STUDIO_JOBS_PREFIX}/{result['job_id']}/outputs/{result_sha}"
        result["attempts"].append(projected_attempt)
    result["results"] = []
    for raw_result in detail.get("results", []):
        if not isinstance(raw_result, dict):
            continue
        projected_result = _safe_browser_value(raw_result)
        projected_result.setdefault("revision_id", result.get("revision_id"))
        digest = projected_result.get("output_sha256")
        if digest and result.get("job_id"):
            projected_result["href"] = f"{STUDIO_JOBS_PREFIX}/{result['job_id']}/outputs/{digest}"
        result["results"].append(projected_result)
    # ``raw_results`` is an explicit alias used by the history screen. It is
    # still metadata only; the body is fetched through the paged href.
    result["raw_results"] = copy.deepcopy(result["results"])
    result["accepted_results"] = _safe_browser_value(detail.get("accepted_results") or [])
    return result


def dispatch_jobs(
    conn,
    control_plane,
    *,
    method: str,
    path: str,
    raw_query: str = "",
    body: bytes = b"",
) -> tuple[int, str, bytes]:
    """Serve one Studio ingestion-job request.

    ``control_plane`` is the ``apps/chronicle/persistence/control_plane.py``
    module (passed in so this router stays importable without persistence on
    sys.path). Returns ``(status, content_type, body_bytes)``.
    """
    from common import PersistenceConflict, PersistenceError

    try:
        return _route(
            conn, control_plane,
            method=method, path=path, raw_query=raw_query, body=body,
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


def _route(conn, control_plane, *, method, path, raw_query, body):
    query = parse_qs(raw_query, keep_blank_values=True)
    if path == STUDIO_JOBS_PREFIX + "/model-options":
        import chapter_model_settings
        if method != "GET" or query:
            raise _BadRequest("model options accepts GET without query parameters")
        return 200, "application/json; charset=utf-8", _json_bytes(chapter_model_settings.catalog(os.environ))


    if path == STUDIO_JOBS_PREFIX + "/history/sources":
        import narrative_store
        if method != "GET" or set(query) - {"limit", "offset"}:
            raise _BadRequest("history sources accepts GET with limit/offset")
        try:
            limit, offset = int(_single(query, "limit") or "50"), int(_single(query, "offset") or "0")
        except ValueError as exc:
            raise _BadRequest("invalid source page") from exc
        return 200, "application/json; charset=utf-8", _json_bytes(narrative_store.list_source_choices(conn, limit=limit, offset=offset))
    if path == STUDIO_JOBS_PREFIX + "/history/model-options":
        import narrative_model_settings
        if method != "GET" or query:
            raise _BadRequest("history model options accepts GET without query parameters")
        return 200, "application/json; charset=utf-8", _json_bytes(narrative_model_settings.catalog(os.environ))
    if path == STUDIO_JOBS_PREFIX + "/history":
        import narrative_store
        if method != "POST" or query:
            raise _BadRequest("history generation accepts POST without query parameters")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise _BadRequest("history generation requires a JSON object") from exc
        if not isinstance(payload, dict) or set(payload) - {"catalog_sha", "publication_ids", "model_selection"}:
            raise _BadRequest("history generation requires catalog_sha and publication_ids; model_selection is optional")
        if set(payload) < {"catalog_sha", "publication_ids"}:
            raise _BadRequest("history generation requires catalog_sha and publication_ids")
        selection = None
        if "model_selection" in payload:
            import narrative_model_settings
            selection = narrative_model_settings.validate_selection(
                payload["model_selection"], narrative_model_settings.catalog(os.environ)
            )
        job_id = narrative_store.queue_narrative(
            conn,
            catalog_sha=payload["catalog_sha"],
            publication_ids=payload["publication_ids"],
            model_selection=selection,
        )
        return _job_response(conn, control_plane, job_id=job_id, status=201)

    if path == STUDIO_JOBS_PREFIX:
        if method == "GET":
            return _list_jobs(conn, control_plane, query=query)
        if method == "POST":
            return _queue_job(conn, control_plane, body=body)
        raise _BadRequest(f"method {method} is not supported on {path}")

    prefix = STUDIO_JOBS_PREFIX + "/"
    if not path.startswith(prefix):
        raise _NotFound("route not found")
    rest = path[len(prefix):]
    parts = rest.split("/")
    if len(parts) == 3 and parts[1] == "outputs":
        import studio_production
        job_id = _require_uuid(parts[0], "job")
        if method != "GET" or set(query) - {"offset", "limit"} or not re.fullmatch(r"[0-9a-f]{64}", parts[2]):
            raise _BadRequest("invalid saved result request")
        try:
            offset, limit = int(_single(query, "offset") or "0"), int(_single(query, "limit") or "16000")
        except ValueError as exc:
            raise _BadRequest("invalid saved result page") from exc
        return 200, "application/json; charset=utf-8", _json_bytes(studio_production.output_page(
            conn, job_id=job_id, digest=parts[2], offset=offset, limit=limit))
    if len(parts) == 2 and parts[1] == "new-run":
        if method != "POST" or query:
            raise _BadRequest("new-run accepts POST without query parameters")
        parent_id = _require_uuid(parts[0], "job")
        parent = control_plane.get_job_detail(conn, job_id=parent_id)
        try:
            options = json.loads(body or b"{}")
        except (ValueError, UnicodeDecodeError) as exc:
            raise _BadRequest("new-run requires a JSON object") from exc
        if not isinstance(options, dict) or set(options) - {"model_selection"}:
            raise _BadRequest("new-run accepts model_selection only")
        selection = None
        if "model_selection" in options:
            if isinstance(parent.get("checkpoint"), dict) and parent["checkpoint"].get("narrative_scope"):
                import narrative_model_settings
                selection = narrative_model_settings.validate_selection(
                    options["model_selection"], narrative_model_settings.catalog(os.environ)
                )
            else:
                import chapter_model_settings
                selection = chapter_model_settings.validate_selection(
                    options["model_selection"], chapter_model_settings.catalog(os.environ)
                )
        import studio_production
        job_id = studio_production.new_run(conn, parent_job_id=parent_id, selection=selection)
        return _job_response(conn, control_plane, job_id=job_id, status=201)
    if len(parts) == 2 and parts[1] == "rerun":
        if method != "POST" or query:
            raise _BadRequest("rerun accepts POST without query parameters")
        parent_id = _require_uuid(parts[0], "job")
        parent = control_plane.get_job_detail(conn, job_id=parent_id)
        try:
            options = json.loads(body or b"{}")
        except ValueError as exc:
            raise _BadRequest("rerun requires a JSON object") from exc
        if not isinstance(options, dict) or set(options) - {"model_selection"}:
            raise _BadRequest("rerun accepts model_selection only")
        return _queue_job(conn, control_plane, body=_json_bytes({**options,
            "revision_id": parent["revision_id"], "max_attempts": parent["max_attempts"]}), parent_job_id=parent_id)
    if len(parts) == 1 and parts[0]:
        job_id = _require_uuid(parts[0], "job")
        if method != "GET":
            raise _BadRequest(f"method {method} is not supported on {path}")
        return _job_response(conn, control_plane, job_id=job_id, status=200)
    if len(parts) == 2 and parts[0] and parts[1] in _JOB_ACTIONS:
        job_id = _require_uuid(parts[0], "job")
        if method != "POST":
            raise _BadRequest(f"method {method} is not supported on {path}")
        action = parts[1]
        if action == "retry":
            control_plane.retry_job(conn, job_id=job_id)
        elif action == "resume":
            control_plane.resume_job(conn, job_id=job_id)
        else:
            control_plane.cancel_job(conn, job_id=job_id)
        return _job_response(conn, control_plane, job_id=job_id, status=200)
    raise _NotFound("route not found")


def _queue_job(conn, control_plane, *, body: bytes, parent_job_id=None) -> tuple[int, str, bytes]:
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _BadRequest(f"request body must be a JSON object: {exc}") from exc
    if not isinstance(payload, dict):
        raise _BadRequest("request body must be a JSON object")
    if set(payload) - {"revision_id", "max_attempts", "model_selection"}:
        raise _BadRequest("unknown production request fields")
    revision_id = payload.get("revision_id")
    if not isinstance(revision_id, str):
        raise _BadRequest("request body must carry a revision_id UUID string")
    revision_uuid = _require_uuid(revision_id, "revision")
    # Content + identity + state review resumes consume claims too. Keep a
    # finite allocation for new Studio jobs without changing lifecycle rules.
    max_attempts = payload.get("max_attempts", 8)
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool):
        raise _BadRequest("max_attempts must be a positive integer")
    import studio_production
    import chapter_model_settings
    selection = None
    if "model_selection" in payload:
        selection = chapter_model_settings.validate_selection(payload["model_selection"], chapter_model_settings.catalog(os.environ))
    job_id = studio_production.queue(conn, revision_id=revision_uuid, max_attempts=max_attempts,
                                    selection=selection, parent_job_id=parent_job_id)
    return _job_response(conn, control_plane, job_id=job_id, status=201)


def _list_jobs(conn, control_plane, *, query: dict[str, list[str]]) -> tuple[int, str, bytes]:
    status = _single(query, "status")
    limit_raw, offset_raw = _single(query, "limit"), _single(query, "offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 100
        offset = int(offset_raw) if offset_raw is not None else 0
    except ValueError as exc:
        raise _BadRequest("limit and offset must be integers") from exc
    import studio_production
    jobs = studio_production.enrich_jobs(
        conn, control_plane.list_jobs(conn, status=status, limit=limit, offset=offset)
    )
    # List and detail use the same browser-safe envelope. The list carries
    # metadata-only stages/results, so this does not embed chapter content.
    jobs = [_studio_job_projection(job) for job in jobs]
    return 200, "application/json; charset=utf-8", _json_bytes(
        {"schema": "chronicle.job-list", "version": "0.1", "jobs": jobs}
    )


def _job_response(
    conn, control_plane, *, job_id: uuid.UUID, status: int
) -> tuple[int, str, bytes]:
    import studio_production
    detail = studio_production.enrich_detail(conn, control_plane.get_job_detail(conn, job_id=job_id))
    return status, "application/json; charset=utf-8", _json_bytes(
        {
            "schema": "chronicle.job",
            "version": "0.3",
            "job": _studio_job_projection(detail),
        }
    )
