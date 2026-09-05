"""Small stdlib helpers for the C1-T17 operator acceptance gate.

This module has no Chronicle persistence imports and no semantic review logic.
It only supplies process, HTTP, configuration, polling, upload, and evidence
helpers used by the strict public gate.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

TERMINAL_JOB_STATES = {"completed", "failed", "cancelled"}


class GateError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True)
    if check and result.returncode != 0:
        raise GateError(
            f"command failed ({result.returncode}): {' '.join(cmd)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def require_live_config(config: dict[str, str]) -> None:
    if config.get("CHRONICLE_MODEL_FIXTURE_PACK", "").strip():
        raise GateError(
            "C1-T17 refuses CHRONICLE_MODEL_FIXTURE_PACK; live provider is required"
        )
    required = (
        "CHRONICLE_POSTGRES_PASSWORD",
        "CHRONICLE_ADMIN_USER",
        "CHRONICLE_ADMIN_PASSWORD",
        "CHRONICLE_MODEL_ENDPOINT",
        "CHRONICLE_EXTRACTION_MODEL",
        "CHRONICLE_PRESENTATION_MODEL",
    )
    missing = [name for name in required if not config.get(name, "").strip()]
    if missing:
        raise GateError(
            f"missing required live-gate configuration: {', '.join(missing)}"
        )
    parsed = urllib.parse.urlparse(config["CHRONICLE_MODEL_ENDPOINT"])
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise GateError("CHRONICLE_MODEL_ENDPOINT must be an absolute http(s) URL")


def safe_provider(config: dict[str, str]) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(config["CHRONICLE_MODEL_ENDPOINT"])
    return {
        "endpoint": urllib.parse.urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, "", "", "")
        ),
        "api_key_present": bool(config.get("CHRONICLE_MODEL_API_KEY", "").strip()),
        "extraction_model": config["CHRONICLE_EXTRACTION_MODEL"],
        "presentation_model": config["CHRONICLE_PRESENTATION_MODEL"],
        "timeout_seconds": config.get("CHRONICLE_MODEL_TIMEOUT_SECONDS", "600"),
        "fixture_mode": False,
    }


def basic_auth(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def http(
    base: str,
    path: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    content_type: str | None = None,
    auth: str | None = None,
    timeout: float = 30.0,
) -> tuple[int, bytes, dict[str, str]]:
    headers = {"Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    if auth:
        headers["Authorization"] = auth
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers.items())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GateError(f"HTTP request failed: {method} {path}") from exc


def json_http(*args: Any, **kwargs: Any) -> tuple[int, dict[str, Any]]:
    status, body, _headers = http(*args, **kwargs)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError(
            f"expected JSON response, got HTTP {status}: {body[:500]!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise GateError(f"expected JSON object, got HTTP {status}: {type(payload).__name__}")
    return status, payload


def require_status(
    status: int,
    expected: int | tuple[int, ...],
    payload: Any,
    label: str,
) -> None:
    allowed = (expected,) if isinstance(expected, int) else expected
    if status not in allowed:
        raise GateError(
            f"{label} returned HTTP {status}, expected {allowed}: {payload}"
        )


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def wait_health(base_url: str, timeout_seconds: int = 120) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            status, _payload = json_http(base_url, "/healthz", timeout=3)
            if status == 200:
                return
        except GateError:
            pass
        time.sleep(1)
    raise GateError("Chronicle web health check did not become ready")


def wait_job(
    base_url: str,
    auth: str,
    job_id: str,
    *,
    wanted: set[str],
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] = {}
    while time.time() < deadline:
        status, payload = json_http(
            base_url,
            f"/api/v1/studio/jobs/{job_id}",
            auth=auth,
        )
        require_status(status, 200, payload, "job detail")
        last = payload["job"]
        if last.get("status") in wanted:
            return last
        if (
            last.get("status") in TERMINAL_JOB_STATES
            and last.get("status") not in wanted
        ):
            raise GateError(f"job entered unexpected terminal state: {last}")
        time.sleep(2)
    raise GateError(f"job did not reach {sorted(wanted)}; last={last}")


def source_query(filename: str, source_label: str) -> str:
    return urllib.parse.urlencode(
        {
            "filename": filename,
            "language": "zh-CN",
            "source_label": source_label,
        }
    )


def upload_revision(
    base_url: str,
    auth: str,
    document_id: str,
    source: Path,
    source_label: str,
) -> dict[str, Any]:
    raw = source.read_bytes()
    status, payload = json_http(
        base_url,
        f"/api/v1/studio/documents/{document_id}/revisions?"
        f"{source_query(source.name, source_label)}",
        method="POST",
        body=raw,
        content_type=(
            "text/markdown" if source.suffix.lower() == ".md" else "text/plain"
        ),
        auth=auth,
        timeout=60,
    )
    require_status(status, (200, 201), payload, "revision upload")
    revision = payload["revision"]
    if revision.get("source_sha256") != sha256_bytes(raw):
        raise GateError("uploaded revision SHA-256 does not match local source")
    return revision


def queue_job(base_url: str, auth: str, revision_id: str) -> dict[str, Any]:
    body = json.dumps({"revision_id": revision_id, "max_attempts": 3}).encode("utf-8")
    status, payload = json_http(
        base_url,
        "/api/v1/studio/jobs",
        method="POST",
        body=body,
        content_type="application/json",
        auth=auth,
    )
    require_status(status, 201, payload, "queue job")
    return payload["job"]


def job_action(
    base_url: str,
    auth: str,
    job_id: str,
    action: str,
) -> dict[str, Any]:
    if action not in {"retry", "resume", "cancel"}:
        raise GateError(f"unsupported Studio job action: {action}")
    status, payload = json_http(
        base_url,
        f"/api/v1/studio/jobs/{job_id}/{action}",
        method="POST",
        body=b"{}",
        content_type="application/json",
        auth=auth,
    )
    require_status(status, 200, payload, f"job {action}")
    return payload["job"]
