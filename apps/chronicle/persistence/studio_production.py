"""Studio projections and explicit new runs over the existing ingestion store.

No second queue or publication authority. Model selection is an immutable
ingestion output committed with the ordinary job; retry never rewrites it.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any

import control_plane
from common import PersistenceConflict, PersistenceError, sha256_json

REQUEST_TYPE = "studio-production-request"
ACCEPTANCE_TYPE = "chapter-production-acceptance"
RESULT_TYPES = (
    "chapter-production-attempt",
    "chapter-production-step",
    "chapter-production-draft",
    ACCEPTANCE_TYPE,
    # Historical narrative model nodes use the same safe output paging
    # surface; prompts, inputs and provider configuration remain excluded by
    # output_page's positive projection below.
    "narrative-plan",
    "narrative-step-attempt",
    "narrative-step",
    # The legacy narrative worker predates the reusable step runner. Its
    # attempt records still belong to the same job/revision and are exposed
    # through the identical redacted result reader.
    "narrative-facts-attempt",
    "narrative-prose-attempt",
    "person-history-plan",
    "person-history-step-attempt",
    "person-history-step",
)
ACCEPTANCE_FIELDS = (
    "schema",
    "version",
    "status",
    "chapter_id",
    "chunk_id",
    "request_fingerprint",
    "pipeline_fingerprint",
    "candidate_sha256",
    "history_sha256",
    "step_output_sha256s",
    "decision",
    "draft_sha256",
)
_SAFE_DECISION_FIELDS = (
    "kind", "decision", "rationale", "plan_fingerprint", "candidate_sha256",
    "history_sha256", "review_output_sha256s", "content_sha256", "review_id",
)

TASK_LABELS = {
    "chapter": "章节生产任务",
    "narrative": "多史料综合任务",
    "person_history": "人物生平任务",
}

STAGE_LABELS = {
    "prepare": "准备",
    "structure": "结构识别",
    "segment": "分段",
    "extract": "内容抽取",
    "assemble": "组装草稿",
    "resolve": "来源核对",
    "publish": "发布",
    "present": "综合呈现",
}

# This is the durable pipeline graph shown to Studio. It is intentionally
# separate from worker implementation details: the latter may add diagnostic
# nodes without changing the operator-facing task graph.
STAGE_DEPENDENCIES = {
    "prepare": (),
    "structure": ("prepare",),
    "segment": ("structure",),
    "extract": ("segment",),
    "assemble": ("extract",),
    "resolve": ("assemble",),
    "publish": ("resolve",),
    "present": ("publish",),
}

ATTEMPT_ARTIFACT_TYPES = frozenset({
    "chapter-production-attempt",
    "narrative-step-attempt",
    "narrative-facts-attempt",
    "narrative-prose-attempt",
    "person-history-step-attempt",
})
RESULT_ARTIFACT_TYPES = frozenset({"chapter-production-step", "narrative-step", "person-history-step"})

_SAFE_USAGE_FIELDS = ("input_tokens", "output_tokens", "total_tokens", "reasoning_tokens")
_SAFE_RECEIPT_FIELDS = (
    "status", "model", "usage", "elapsed_seconds", "http_attempts",
    "output_complete", "started_at", "finished_at", "ended_at",
)
_PRIVATE_KEY_PARTS = (
    "api_key", "apikey", "authorization", "password", "secret", "credential",
    "access_token", "refresh_token", "private_key", "model_config", "transport",
    "endpoint", "url", "server_path", "storage_path", "storage_key", "filesystem_path", "path",
    "headers", "prompt",
)


def _private_key(key: Any) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return normalized in {"token", "input"} or any(part in normalized for part in _PRIVATE_KEY_PARTS)


def safe_json_value(value: Any) -> Any:
    """Recursively keep model result data while dropping secret-shaped keys.

    Result bodies are user-visible model material, so a blanket string
    scrubber would corrupt historical prose. The boundary is instead a
    positive field projection plus this nested key denylist for accidentally
    embedded credentials, transport configuration, or server paths.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [safe_json_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): safe_json_value(item)
            for key, item in value.items()
            if not _private_key(key)
        }
    return str(value)


def safe_error(value: Any) -> str | None:
    """Redact credentials and server locations from diagnostic text."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
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


def safe_diagnostic(value: Any) -> Any:
    if isinstance(value, str):
        return safe_error(value)
    if isinstance(value, list):
        return [safe_diagnostic(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): safe_diagnostic(item)
            for key, item in value.items()
            if not _private_key(key)
        }
    return safe_json_value(value)


def safe_usage(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    result = {
        key: value[key]
        for key in _SAFE_USAGE_FIELDS
        if isinstance(value.get(key), int)
        and not isinstance(value[key], bool)
        and value[key] >= 0
    }
    return result or None


def _sha256_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and re.fullmatch(r"[0-9a-f]{64}", item)]


def safe_decision(value: Any) -> Any:
    """Keep acceptance decision metadata while excluding candidate bodies."""
    if not isinstance(value, dict):
        return value if isinstance(value, (str, int, float, bool)) or value is None else str(value)
    result: dict[str, Any] = {}
    for key in _SAFE_DECISION_FIELDS:
        if key not in value:
            continue
        item = value[key]
        if key == "review_output_sha256s":
            result[key] = _sha256_list(item)
        elif key == "rationale" and isinstance(item, str):
            result[key] = safe_error(item)
        elif isinstance(item, (str, int, float, bool)) or item is None:
            result[key] = item
    return result


def safe_receipt(value: Any) -> dict[str, Any]:
    """Expose bounded provider accounting, never the provider request."""
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key in _SAFE_RECEIPT_FIELDS:
        if key not in value:
            continue
        item = value[key]
        if key == "usage":
            result[key] = safe_usage(item)
        elif key in ("elapsed_seconds",) and isinstance(item, (int, float)) and not isinstance(item, bool) and item >= 0:
            result[key] = item
        elif key in ("http_attempts",) and isinstance(item, int) and not isinstance(item, bool) and item >= 0:
            result[key] = item
        elif key == "output_complete" and isinstance(item, bool):
            result[key] = item
        elif isinstance(item, str):
            result[key] = item
    return result


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _elapsed(started_at: str | None, ended_at: str | None, receipt: dict[str, Any]) -> float | int | None:
    value = receipt.get("elapsed_seconds")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return value
    if started_at and ended_at:
        try:
            seconds = (datetime.fromisoformat(ended_at) - datetime.fromisoformat(started_at)).total_seconds()
        except (TypeError, ValueError):
            return None
        return round(seconds, 3) if seconds >= 0 else None
    return None


def _output_complete(payload: dict[str, Any], status: str | None, receipt: dict[str, Any]) -> bool:
    explicit = payload.get("output_complete")
    if isinstance(explicit, bool):
        return explicit
    if status in ("failed", "cancelled", "invalid") or receipt.get("status") in (
        "failed", "cancelled", "invalid"
    ):
        return False
    # Legacy narrative attempts encode a provider/validation failure on the
    # attempt row itself and have no separate result status. Such a response
    # is retained for audit, but it is not a complete successful output.
    if payload.get("error") or payload.get("validation_error") or payload.get("validation_errors"):
        return False
    raw = payload.get("raw_text", payload.get("raw_response"))
    return isinstance(raw, str) and bool(raw)


def _validation_projection(payload: dict[str, Any], status: str | None) -> dict[str, Any]:
    errors = payload.get("validation_errors")
    if errors is None and payload.get("validation_error") is not None:
        errors = [payload.get("validation_error")]
    safe_errors = safe_diagnostic(errors) if errors is not None else []
    if not isinstance(safe_errors, list):
        safe_errors = [safe_errors]
    if status == "completed" and not safe_errors:
        state = "passed"
    elif safe_errors or status in ("invalid", "failed"):
        state = "failed"
    else:
        state = "unreported"
    return {"status": state, "errors": safe_errors}


def _comparison_status(payload: dict[str, Any], status: str | None, complete: bool) -> str:
    step = str(payload.get("step") or "")
    parsed = payload.get("parsed") if isinstance(payload.get("parsed"), dict) else {}
    is_comparison = step.endswith("compare") or any(
        key in parsed for key in ("selected_sha256", "disagreements", "differences")
    )
    if not is_comparison:
        return "not_applicable"
    # A failed/incomplete result must never be presented as agreement, even
    # when an old or malformed parsed payload contains a selected hash.
    has_validation_error = bool(
        payload.get("error") or payload.get("validation_error") or payload.get("validation_errors")
    )
    if status != "completed" or not complete or has_validation_error:
        return "unavailable"
    if parsed.get("disagreements") or any(
        isinstance(item, dict) and item.get("assessment") == "disputed"
        for item in (parsed.get("differences") or [])
    ):
        return "disputed"
    if isinstance(parsed.get("selected_sha256"), str):
        return "agreed"
    return "unreported"


def _attempt_key(payload: dict[str, Any]) -> tuple[Any, ...]:
    return (
        payload.get("node_key") or payload.get("kind") or payload.get("step"),
        payload.get("step"), payload.get("round"), payload.get("slot"),
        payload.get("attempt") or payload.get("attempt_sequence"),
    )


def _attempt_projection(
    *,
    start: dict[str, Any] | None,
    start_digest: str | None,
    start_created_at: Any,
    result: dict[str, Any] | None,
    result_digest: str | None,
    result_created_at: Any,
) -> dict[str, Any]:
    source = result or start or {}
    receipt = safe_receipt(source.get("receipt"))
    status = source.get("status")
    if not isinstance(status, str) and start is not None:
        status = start.get("status")
    if not isinstance(status, str) and source.get("validation_error"):
        status = "failed"
    started = source.get("started_at") if result is not None else None
    if not isinstance(started, str) and start is not None:
        started = start.get("started_at")
    if not isinstance(started, str):
        started = _iso(start_created_at or result_created_at)
    ended = source.get("ended_at") or source.get("finished_at")
    if not isinstance(ended, str):
        ended = receipt.get("ended_at") or receipt.get("finished_at")
    if not isinstance(ended, str) and result is not None:
        ended = _iso(result_created_at)
    complete = _output_complete(source, status, receipt)
    validation = _validation_projection(source, status)
    usage = safe_usage(receipt.get("usage"))
    step = source.get("step") or (start or {}).get("step") or (start or {}).get("kind")
    attempt = source.get("attempt") or source.get("attempt_sequence") or (start or {}).get("attempt")
    output_sha = result_digest or start_digest
    return {
        "attempt_id": start_digest or result_digest,
        "attempt_sha256": start_digest,
        "result_sha256": result_digest,
        "output_sha256": output_sha,
        "artifact_type": (result or start or {}).get("artifact_type"),
        "step": step,
        "slot": source.get("slot") or (start or {}).get("slot"),
        "model": source.get("model") or (start or {}).get("model"),
        "round": source.get("round") if source.get("round") is not None else (start or {}).get("round"),
        "attempt": attempt,
        "attempt_count": attempt,
        "status": status,
        "started_at": started,
        "ended_at": ended,
        "elapsed_seconds": _elapsed(started, ended, receipt),
        "output_complete": complete,
        "validation": validation,
        "validation_status": validation["status"],
        "comparison_status": _comparison_status(source, status, complete),
        "usage": usage,
        "usage_status": "reported" if usage is not None else "unreported",
    }


def read_request(conn, job_id):
    rows = conn.execute(
        "SELECT artifact_sha256, payload FROM chronicle.ingestion_outputs WHERE job_id = %s AND artifact_type = %s",
        (job_id, REQUEST_TYPE),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1 or sha256_json(rows[0][1]) != rows[0][0]:
        raise PersistenceConflict("production request changed")
    return rows[0][1]


def queue(conn, *, revision_id, max_attempts=8, selection=None, parent_job_id=None):
    with conn.transaction():
        if parent_job_id is not None:
            parent = conn.execute(
                "SELECT revision_id, status, checkpoint FROM chronicle.ingestion_jobs WHERE job_id = %s FOR UPDATE",
                (parent_job_id,),
            ).fetchone()
            if parent is None:
                raise PersistenceError("unknown parent job")
            if parent[0] != revision_id or parent[1] not in ("failed", "cancelled"):
                raise PersistenceConflict("only a failed or cancelled task can start a linked rerun")
            if {"narrative_scope", "person_history_scope"} & set(parent[2] or {}):
                raise PersistenceConflict("select published sources to create a new source-grounded task")
        job_id = control_plane.queue_job(conn, revision_id=revision_id, max_attempts=max_attempts)
        if selection is not None or parent_job_id is not None:
            value = {"version": "0.1", "model_selection": selection,
                     "parent_job_id": str(parent_job_id) if parent_job_id else None}
            control_plane.record_output(conn, job_id=job_id, revision_id=revision_id,
                artifact_type=REQUEST_TYPE, artifact_sha256=sha256_json(value), payload=value)
        return job_id


def new_run(conn, *, parent_job_id: uuid.UUID, selection=None):
    """Create a fresh run while preserving the parent's source relationship.

    Chapter runs use the ordinary production queue. Narrative runs reuse the
    frozen catalog/publication selection and enter through
    ``narrative_store.queue_narrative`` so the source lock, revision binding,
    and parent link are all checked by the existing persistence authorities.
    """
    parent = control_plane.get_job_detail(conn, job_id=parent_job_id)
    if parent.get("status") not in ("failed", "cancelled"):
        raise PersistenceConflict("only a failed or cancelled task can start a linked rerun")
    checkpoint = parent.get("checkpoint") if isinstance(parent.get("checkpoint"), dict) else {}
    person_scope = checkpoint.get("person_history_scope")
    narrative_scope = checkpoint.get("narrative_scope")
    if isinstance(person_scope, dict):
        import person_history_store
        request = read_request(conn, parent_job_id)
        chosen = selection
        if chosen is None and isinstance(request, dict):
            chosen = request.get("model_selection")
        return person_history_store.queue_person_history(
            conn,
            person_id=person_scope.get("person_id"),
            catalog_sha=person_scope.get("catalog_sha"),
            publication_ids=person_scope.get("publication_ids"),
            model_selection=chosen,
            parent_job_id=parent_job_id,
        )
    if isinstance(narrative_scope, dict):
        import narrative_store
        request = read_request(conn, parent_job_id)
        chosen = selection
        if chosen is None and isinstance(request, dict):
            chosen = request.get("model_selection")
        return narrative_store.queue_narrative(
            conn,
            catalog_sha=narrative_scope.get("catalog_sha"),
            publication_ids=narrative_scope.get("publication_ids"),
            model_selection=chosen,
            parent_job_id=parent_job_id,
        )
    return queue(
        conn,
        revision_id=uuid.UUID(parent["revision_id"]),
        max_attempts=int(parent["max_attempts"]),
        selection=selection,
        parent_job_id=parent_job_id,
    )


def _current_stage(stage_rows: list[tuple[str, str]]) -> str | None:
    """Choose the operator's current stage from persisted stage status."""
    order = {name: index for index, name in enumerate(control_plane.STAGE_NAMES)}
    for wanted in (("running", "needs_review", "failed"), ("pending",), ("completed",), ("skipped",)):
        choices = [stage for stage, status in stage_rows if status in wanted]
        if choices:
            return min(choices, key=lambda value: order.get(value, len(order))) if wanted != ("completed",) else max(
                choices, key=lambda value: order.get(value, -1)
            )
    return None


def _source_count(scope: Any) -> int:
    if not isinstance(scope, dict):
        return 1
    publication_ids = scope.get("publication_ids")
    return len(publication_ids) if isinstance(publication_ids, list) else 0


def _narrative_scope_validation(conn, scope: Any) -> tuple[bool | None, str | None]:
    """Run the same frozen-source validation used by narrative execution."""
    if not isinstance(scope, dict):
        return None, None
    try:
        if scope.get("person_id") is not None:
            import person_history_store
            person_history_store.validate_source_scope(
                conn,
                person_id=scope.get("person_id"),
                catalog_sha=scope.get("catalog_sha"),
                publication_ids=scope.get("publication_ids"),
            )
        else:
            import narrative_store
            narrative_store.validate_source_scope(
                conn,
                catalog_sha=scope.get("catalog_sha"),
                publication_ids=scope.get("publication_ids"),
            )
    except (PersistenceConflict, PersistenceError) as exc:
        return False, safe_error(str(exc)) or "冻结来源不可用"
    return True, None


def _action_state(
    conn,
    *,
    job_id: uuid.UUID | str,
    status: str,
    attempt: int,
    max_attempts: int,
    open_reviews: int,
    narrative_scope: Any,
) -> dict[str, Any]:
    scope_valid, scope_reason = _narrative_scope_validation(conn, narrative_scope)
    return control_plane.action_state_from_values(
        job_id=job_id,
        status=status,
        attempt=attempt,
        max_attempts=max_attempts,
        open_reviews=open_reviews,
        narrative_scope=narrative_scope if isinstance(narrative_scope, dict) else None,
        narrative_scope_valid=scope_valid,
        narrative_scope_reason=scope_reason,
    )


def _stage_projection(stage_rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
    """Project the durable stage graph without copying stage checkpoints."""
    statuses = {
        row[0]: row[1]
        for row in stage_rows
        if len(row) >= 2 and isinstance(row[0], str)
    }
    projected: list[dict[str, Any]] = []
    for row in stage_rows:
        if len(row) < 2 or not isinstance(row[0], str):
            continue
        stage, status = row[0], row[1]
        attempt = row[2] if len(row) > 2 else None
        error = row[3] if len(row) > 3 else None
        started_at = row[4] if len(row) > 4 else None
        finished_at = row[5] if len(row) > 5 else None
        dependencies = list(STAGE_DEPENDENCIES.get(stage, ()))
        dependency_statuses = [statuses.get(dependency) for dependency in dependencies]
        blocked_reason = None
        if status == "pending" and any(
            dependency in ("failed", "needs_review") for dependency in dependency_statuses
        ):
            blocked_reason = "前置步骤未完成"
        elif status == "pending" and any(
            dependency not in ("completed", "skipped") for dependency in dependency_statuses
        ):
            blocked_reason = "等待前置步骤"
        projected.append({
            "key": stage,
            "machine_key": stage,
            "stage": stage,
            "label": STAGE_LABELS.get(stage, "步骤"),
            "status": status,
            "attempt": attempt,
            "dependencies": dependencies,
            "error": error,
            "failure_reason": error,
            "blocked_reason": blocked_reason,
            "started_at": _iso(started_at),
            "finished_at": _iso(finished_at),
        })
    order = {name: index for index, name in enumerate(control_plane.STAGE_NAMES)}
    return sorted(projected, key=lambda item: order.get(item["key"], len(order)))


def _action_projection(job_id: str, state: dict[str, Any]) -> list[dict[str, Any]]:
    labels = {
        "retry": "重试",
        "resume": "继续生产",
        "cancel": "取消任务",
        "new_run": "新建运行",
    }
    paths = {"new_run": "new-run"}
    return [
        {
            **item,
            "label": labels.get(item["key"], item["key"]),
            "method": "POST",
            "href": f"/api/v1/studio/jobs/{job_id}/{paths.get(item['key'], item['key'])}",
        }
        for item in state.get("actions", [])
    ]


def _task_projection(*, kind: str, title: str, source_count: int) -> dict[str, Any]:
    return {
        "type": kind,
        "machine_key": kind,
        "label": TASK_LABELS.get(kind, "任务"),
        "title": title,
        "source_count": source_count,
    }


def enrich_jobs(conn, jobs):
    """Batch readable names and current state; never fetch one detail per row."""
    if not jobs:
        return jobs
    job_ids = [uuid.UUID(job["job_id"]) for job in jobs]
    rows = conn.execute(
        """SELECT j.job_id, d.document_id, d.title, r.revision_no, r.filename,
                  CASE WHEN j.checkpoint ? 'person_history_scope' THEN 'person_history'
                       WHEN j.checkpoint ? 'narrative_scope' THEN 'narrative'
                       ELSE 'chapter' END,
                  COALESCE(j.checkpoint->'person_history_scope', j.checkpoint->'narrative_scope'),
                  (SELECT count(*) FROM chronicle.review_items ri WHERE ri.job_id=j.job_id AND ri.status='open')
           FROM chronicle.ingestion_jobs j
           JOIN chronicle.document_revisions r ON r.revision_id=j.revision_id
           JOIN chronicle.documents d ON d.document_id=r.document_id
           WHERE j.job_id=ANY(%s)""", (job_ids,),
    ).fetchall()
    stage_rows = conn.execute(
        """SELECT job_id, stage, status, attempt, error, started_at, finished_at
           FROM chronicle.ingestion_job_stages
           WHERE job_id=ANY(%s) ORDER BY job_id, stage""", (job_ids,),
    ).fetchall()
    stages_by_job: dict[str, list[tuple[Any, ...]]] = {}
    for job_id, stage, status, attempt, error, started_at, finished_at in stage_rows:
        stages_by_job.setdefault(str(job_id), []).append(
            (stage, status, int(attempt), error, started_at, finished_at)
        )
    source_metadata = {}
    scope_by_job: dict[str, dict[str, Any] | None] = {}
    for job, document, title, revision, filename, kind, scope, reviews in rows:
        job_key = str(job)
        if kind not in TASK_LABELS:
            kind = "chapter"
        stage_rows_for_job = stages_by_job.get(job_key, [])
        source_count = _source_count(scope)
        current = _current_stage([(row[0], row[1]) for row in stage_rows_for_job])
        stages = _stage_projection(stage_rows_for_job)
        scope_by_job[job_key] = scope if isinstance(scope, dict) else None
        source_metadata[job_key] = {
            "document": {"document_id": str(document), "title": title,
                         "revision_no": revision, "filename": filename},
            "job_kind": kind,
            "job_kind_label": TASK_LABELS[kind],
            "task": _task_projection(kind=kind, title=title, source_count=source_count),
            "title": title,
            "source_count": source_count,
            "open_reviews": int(reviews),
            "current_stage": current,
            "stages": stages,
        }
    enriched = []
    for job in jobs:
        metadata = source_metadata.get(job["job_id"])
        if metadata is None:
            enriched.append(dict(job))
            continue
        state = _action_state(
            conn,
            job_id=job["job_id"],
            status=job["status"],
            attempt=int(job["attempt"]),
            max_attempts=int(job["max_attempts"]),
            open_reviews=metadata["open_reviews"],
            narrative_scope=scope_by_job.get(job["job_id"]),
        )
        current = metadata["current_stage"]
        stages = metadata["stages"]
        current_step = next((stage for stage in stages if stage["key"] == current), None)
        enriched.append({
            **job,
            **metadata,
            "current_step": {
                "key": current,
                "machine_key": current,
                "label": STAGE_LABELS.get(current) if current else None,
                "status": current_step["status"] if current_step else None,
                "failure_reason": current_step["failure_reason"] if current_step else None,
            },
            "stages": stages,
            "steps": [dict(stage) for stage in stages],
            "step_graph": {
                "current_step": current,
                "steps": [dict(stage) for stage in stages],
                "dependencies": {
                    stage["key"]: list(stage["dependencies"]) for stage in stages
                },
            },
            "action_state": state,
            "actions": _action_projection(job["job_id"], state),
            "available_actions": state["available_actions"],
            "action_reasons": state["action_reasons"],
        })
    return enriched


def enrich_detail(conn, detail):
    result = enrich_jobs(conn, [detail])[0]
    control_state = control_plane.job_action_state(
        conn, job_id=uuid.UUID(str(detail["job_id"]))
    )
    checkpoint = detail.get("checkpoint") if isinstance(detail.get("checkpoint"), dict) else {}
    scope = checkpoint.get("person_history_scope") or checkpoint.get("narrative_scope")
    result["action_state"] = _action_state(
        conn,
        job_id=detail["job_id"],
        status=control_state["status"],
        attempt=control_state["attempt"],
        max_attempts=control_state["max_attempts"],
        open_reviews=control_state["open_reviews"],
        narrative_scope=scope,
    )
    result["actions"] = _action_projection(detail["job_id"], result["action_state"])
    result["available_actions"] = result["action_state"]["available_actions"]
    result["action_reasons"] = result["action_state"]["action_reasons"]
    labels = dict(conn.execute(
        "SELECT section_id, label FROM chronicle.ingestion_sections WHERE job_id=%s", (detail["job_id"],),
    ).fetchall())
    for chunk in result["chunks"]:
        chunk["title"] = labels.get(uuid.UUID(chunk["section_id"])) if chunk.get("section_id") else None
    request = read_request(conn, detail["job_id"])
    if isinstance(request, dict):
        # Request rows are durable audit material, not a transport/config
        # response. Keep only the fields needed to reproduce the selection
        # relationship; nested key filtering handles a tampered row too.
        result["production_request"] = {
            key: safe_json_value(request[key])
            for key in ("version", "model_selection", "parent_job_id")
            if key in request
        }
    else:
        result["production_request"] = None
    result["narrative_acceptances"] = [
        {
            "acceptance_id": str(row[0]),
            "kind": row[1],
            "acceptance_type": row[2],
            "policy_version": row[3],
            "input_sha256": row[4],
            "candidate_sha256": row[5],
            "draft_sha256": row[6],
            "content_sha256": row[7],
            "pipeline_fingerprint": row[8],
            "model_output_sha256s": _sha256_list(row[9]),
            "model_opinion_sha256s": _sha256_list(row[10]),
            "decision": row[11],
            "decision_reason": row[12],
            "review_id": str(row[13]) if row[13] is not None else None,
            "created_at": row[14].isoformat() if row[14] is not None else None,
            "receipt_sha256": row[15].get("receipt_sha256") if isinstance(row[15], dict) else None,
            "reviewed_conclusion_ids": list(row[15].get("reviewed_conclusion_ids") or [])
                if isinstance(row[15], dict) else [],
        }
        for row in conn.execute(
            """
            SELECT acceptance_id, kind, acceptance_type, policy_version,
                   input_sha256, candidate_sha256, draft_sha256, content_sha256,
                   pipeline_fingerprint, model_output_sha256s, model_opinion_sha256s,
                   decision, decision_reason, review_id, created_at, payload
            FROM chronicle.narrative_acceptances
            WHERE job_id = %s
            UNION ALL
            SELECT acceptance_id, kind, acceptance_type, policy_version,
                   input_sha256, candidate_sha256, draft_sha256, content_sha256,
                   pipeline_fingerprint, model_output_sha256s, model_opinion_sha256s,
                   decision, decision_reason, review_id, created_at, payload
            FROM chronicle.person_history_acceptances
            WHERE job_id = %s
            ORDER BY created_at, acceptance_id
            """,
            (detail["job_id"], detail["job_id"]),
        ).fetchall()
    ]
    # Explicit result metadata, with all attempts (not only the latest node
    # checkpoint). Large model bodies are read only when an operator opens one.
    # The payload is used only to derive a positive metadata projection here;
    # it is never attached to the detail response.
    rows = conn.execute(
        """SELECT output_id, artifact_type, artifact_sha256, created_at, payload
           FROM chronicle.ingestion_outputs WHERE job_id=%s AND artifact_type=ANY(%s)
           ORDER BY created_at, output_id""", (detail["job_id"], list(RESULT_TYPES)),
    ).fetchall()
    by_digest = {row[2]: row for row in rows}
    for output in result["outputs"]:
        row = by_digest.get(output["artifact_sha256"])
        if row:
            payload = row[4] if isinstance(row[4], dict) else {}
            output.update({
                key: payload[key]
                for key in ("step", "model", "status", "chunk_id", "attempt", "round", "slot")
                if key in payload and isinstance(payload[key], (str, int, float))
                and not isinstance(payload[key], bool)
            })
            output["created_at"] = _iso(row[3])
            output["readable"] = True

    # Pair durable attempt starts with their result by the immutable
    # attempt_sha256 relation. Legacy narrative records have no result row,
    # which is intentional: the operator can still page the saved raw response
    # and sees output_complete/validation as unreported when the old schema
    # did not record it.
    starts: list[tuple[str, Any, Any]] = []
    results: list[tuple[str, Any, Any]] = []
    for _output_id, artifact_type, digest, created_at, raw_payload in rows:
        payload = dict(raw_payload) if isinstance(raw_payload, dict) else {}
        payload["artifact_type"] = artifact_type
        if artifact_type in ATTEMPT_ARTIFACT_TYPES:
            starts.append((digest, payload, created_at))
        elif artifact_type in RESULT_ARTIFACT_TYPES:
            results.append((digest, payload, created_at))
    result_by_attempt = {
        payload.get("attempt_sha256"): (digest, payload, created_at)
        for digest, payload, created_at in results
        if isinstance(payload.get("attempt_sha256"), str)
    }
    results_by_key: dict[tuple[Any, ...], list[tuple[str, dict[str, Any], Any]]] = {}
    for entry in results:
        results_by_key.setdefault(_attempt_key(entry[1]), []).append(entry)
    used_results: set[str] = set()
    attempts: list[dict[str, Any]] = []
    for start_digest, start_payload, start_created_at in starts:
        match = result_by_attempt.get(start_digest)
        if match is None:
            candidates = results_by_key.get(_attempt_key(start_payload), [])
            match = next((entry for entry in candidates if entry[0] not in used_results), None)
        if match is not None:
            used_results.add(match[0])
        attempts.append(_attempt_projection(
            start=start_payload,
            start_digest=start_digest,
            start_created_at=start_created_at,
            result=match[1] if match else None,
            result_digest=match[0] if match else None,
            result_created_at=match[2] if match else None,
        ))
    for result_digest, result_payload, result_created_at in results:
        if result_digest in used_results:
            continue
        attempts.append(_attempt_projection(
            start=None,
            start_digest=None,
            start_created_at=None,
            result=result_payload,
            result_digest=result_digest,
            result_created_at=result_created_at,
        ))
    result["attempts"] = attempts
    result["results"] = [
        {
            "output_sha256": digest,
            "artifact_type": artifact_type,
            "created_at": _iso(created_at),
            "step": payload.get("step"),
            "model": payload.get("model"),
            "status": payload.get("status"),
            "attempt": payload.get("attempt") or payload.get("attempt_sequence"),
            "round": payload.get("round"),
            "readable": True,
        }
        for _output_id, artifact_type, digest, created_at, payload in rows
        if artifact_type in ATTEMPT_ARTIFACT_TYPES | RESULT_ARTIFACT_TYPES
    ]
    # A stable source relationship is useful to T08 and does not expose the
    # revision's storage key or any server-side path.
    document = result.get("document") if isinstance(result.get("document"), dict) else {}
    result["source"] = {
        "revision_id": result.get("revision_id"),
        "document_id": document.get("document_id"),
        "revision_no": document.get("revision_no"),
        "source_count": result.get("source_count"),
        "relationship": "immutable_revision",
    }
    accepted_results: list[dict[str, Any]] = []
    for acceptance in result["narrative_acceptances"]:
        accepted_results.append({
            "acceptance_id": acceptance["acceptance_id"],
            "kind": acceptance["kind"],
            "acceptance_type": acceptance["acceptance_type"],
            "policy_version": acceptance["policy_version"],
            "input_sha256": acceptance["input_sha256"],
            "candidate_sha256": acceptance["candidate_sha256"],
            "draft_sha256": acceptance["draft_sha256"],
            "content_sha256": acceptance["content_sha256"],
            "pipeline_fingerprint": acceptance["pipeline_fingerprint"],
            "model_output_sha256s": acceptance["model_output_sha256s"],
            "model_opinion_sha256s": acceptance["model_opinion_sha256s"],
            "decision": acceptance["decision"],
            "review_id": acceptance["review_id"],
            "created_at": acceptance["created_at"],
        })
    for output in result["outputs"]:
        if output.get("artifact_type") != ACCEPTANCE_TYPE:
            continue
        row = by_digest.get(output["artifact_sha256"])
        payload = row[4] if row and isinstance(row[4], dict) else {}
        decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
        step_output_sha256s = _sha256_list(payload.get("step_output_sha256s"))
        accepted_results.append({
            "acceptance_id": None,
            "kind": "chapter",
            "acceptance_type": "chapter",
            "status": payload.get("status"),
            "candidate_sha256": payload.get("candidate_sha256"),
            "draft_sha256": payload.get("draft_sha256"),
            "pipeline_fingerprint": payload.get("pipeline_fingerprint"),
            "history_sha256": payload.get("history_sha256"),
            "step_output_sha256s": step_output_sha256s,
            "model_output_sha256s": step_output_sha256s,
            "model_opinion_sha256s": _sha256_list(decision.get("review_output_sha256s")),
            "decision": safe_decision(decision),
            "review_id": None,
            "receipt_sha256": output["artifact_sha256"],
        })
    result["accepted_results"] = accepted_results
    accepted_by_digest: dict[str, list[dict[str, Any]]] = {}
    for accepted in accepted_results:
        for role, field in (("model_output", "model_output_sha256s"), ("model_opinion", "model_opinion_sha256s")):
            for digest in accepted.get(field) or []:
                accepted_by_digest.setdefault(digest, []).append({
                    "role": role, "acceptance_id": accepted.get("acceptance_id"),
                    "kind": accepted.get("kind"),
                })
    for output in result["outputs"]:
        links = accepted_by_digest.get(output["artifact_sha256"])
        if links:
            output["acceptance_links"] = links
    return result


def _safe_result_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return one pageable result body without request/transport material."""
    if kind == ACCEPTANCE_TYPE:
        return {
            key: safe_decision(payload[key]) if key == "decision" else safe_json_value(payload[key])
            for key in ACCEPTANCE_FIELDS
            if key in payload
        }
    fields = (
        "schema", "version", "kind", "step", "node_key", "slot", "model",
        "round", "attempt", "attempt_sequence", "status", "started_at",
        "ended_at", "finished_at", "attempt_sha256", "input_sha256",
        "context_sha", "context_sha256", "pipeline_fingerprint",
        "request_fingerprint", "retry_of", "raw_text", "raw_response",
        "parsed", "candidate", "issues", "validation_errors",
        "validation_error", "error", "output_complete", "receipt",
    )
    safe: dict[str, Any] = {}
    for key in fields:
        if key not in payload:
            continue
        if key == "receipt":
            safe[key] = safe_receipt(payload[key])
        elif key in ("error", "validation_error", "validation_errors"):
            safe[key] = safe_diagnostic(payload[key])
        else:
            safe[key] = safe_json_value(payload[key])
    return safe


def output_page(conn, *, job_id, digest, offset=0, limit=16000):
    if (isinstance(offset, bool) or not isinstance(offset, int) or offset < 0
            or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 16000):
        raise PersistenceError("invalid result page bounds")
    row = conn.execute(
        """SELECT o.artifact_type, o.revision_id, o.payload FROM chronicle.ingestion_outputs o
           JOIN chronicle.ingestion_jobs j ON j.job_id=o.job_id AND j.revision_id=o.revision_id
           WHERE o.job_id=%s AND o.artifact_sha256=%s AND o.artifact_type=ANY(%s)""",
        (job_id, digest, list(RESULT_TYPES)),
    ).fetchone()
    if row is None:
        raise PersistenceError("unknown task result")
    kind, revision_id, payload = row
    if not isinstance(payload, dict) or sha256_json(payload) != digest:
        raise PersistenceConflict("saved task result changed")
    # A positive allowlist: prompts, provider configuration, credentials,
    # inputs and unrecognized transport fields never reach the browser. The
    # acceptance receipt is a separate safe result: it contains only hashes,
    # decision metadata and its chunk binding, never the candidate body.
    safe = _safe_result_payload(kind, payload)
    text = json.dumps(safe, ensure_ascii=False, indent=2)
    if offset > len(text):
        raise PersistenceError("result page is outside the saved output")
    end = min(len(text), offset + limit)
    return {"job_id": str(job_id), "revision_id": str(revision_id), "output_sha256": digest, "artifact_type": kind,
            "text": text[offset:end], "offset": offset, "total_chars": len(text),
            "next_offset": end if end < len(text) else None}
