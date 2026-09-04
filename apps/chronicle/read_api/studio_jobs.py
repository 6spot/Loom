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

All responses are JSON under a ``chronicle.*`` schema:

```text
POST   /api/v1/studio/jobs                        {"revision_id": "..."}
GET    /api/v1/studio/jobs[?status=&limit=&offset=]
GET    /api/v1/studio/jobs/{job_id}
POST   /api/v1/studio/jobs/{job_id}/retry
POST   /api/v1/studio/jobs/{job_id}/resume
POST   /api/v1/studio/jobs/{job_id}/cancel
```
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.parse import parse_qs

STUDIO_JOBS_PREFIX = "/api/v1/studio/jobs"

_JOB_ACTIONS = ("retry", "resume", "cancel")


def _error(status: int, code: str, message: str) -> tuple[int, str, bytes]:
    payload = {
        "schema": "chronicle.error",
        "version": "0.1",
        "error": {"code": code, "message": message},
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
    module (passed in so this router stays importable without persistence
    on sys.path). Returns ``(status, content_type, body_bytes)``.
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


def _queue_job(conn, control_plane, *, body: bytes) -> tuple[int, str, bytes]:
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _BadRequest(f"request body must be a JSON object: {exc}") from exc
    if not isinstance(payload, dict):
        raise _BadRequest("request body must be a JSON object")
    revision_id = payload.get("revision_id")
    if not isinstance(revision_id, str):
        raise _BadRequest("request body must carry a revision_id UUID string")
    revision_uuid = _require_uuid(revision_id, "revision")
    max_attempts = payload.get("max_attempts", 3)
    if not isinstance(max_attempts, int):
        raise _BadRequest("max_attempts must be a positive integer")
    job_id = control_plane.queue_job(conn, revision_id=revision_uuid, max_attempts=max_attempts)
    return _job_response(conn, control_plane, job_id=job_id, status=201)


def _list_jobs(conn, control_plane, *, query: dict[str, list[str]]) -> tuple[int, str, bytes]:
    status = _single(query, "status")
    limit_raw, offset_raw = _single(query, "limit"), _single(query, "offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 100
        offset = int(offset_raw) if offset_raw is not None else 0
    except ValueError as exc:
        raise _BadRequest("limit and offset must be integers") from exc
    jobs = control_plane.list_jobs(conn, status=status, limit=limit, offset=offset)
    return 200, "application/json; charset=utf-8", _json_bytes(
        {"schema": "chronicle.job-list", "version": "0.1", "jobs": jobs}
    )


def _job_response(
    conn, control_plane, *, job_id: uuid.UUID, status: int
) -> tuple[int, str, bytes]:
    detail = control_plane.get_job_detail(conn, job_id=job_id)
    return status, "application/json; charset=utf-8", _json_bytes(
        {"schema": "chronicle.job", "version": "0.1", "job": detail}
    )
