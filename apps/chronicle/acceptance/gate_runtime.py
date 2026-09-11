"""Shared lifecycle and evidence runtime for Chronicle acceptance gates.

The first-round offline gate (``first_round_gate.py``) and the second-round
continuous-reading gate (``second_round_gate.py``) both need the same
process/HTTP/evidence helpers and, for stack-backed runs, the same isolated
Docker Compose lifecycle. This module is the single home for that shared
runtime so a second gate never copies a parallel product-write or stack
lifecycle path.

Boundary: this module carries no Chronicle semantic/persistence logic. It
only supplies generic process, HTTP, source-pack, evidence and container
helpers. Product mutations always go through the public HTTP API or the
product acceptance entries owned by the calling gate.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Sequence

TERMINAL_JOB_STATES = {"completed", "failed", "cancelled"}

#: Compose project prefix: isolated gates must never touch the operator's
#: default project or the repository-managed PostgreSQL test service.
GATE_PROJECT_PREFIX = "chronicle-gate"


class GateError(RuntimeError):
    """Fail-closed acceptance error surfaced by every gate entry."""


# ---------------------------------------------------------------------------
# Hashing / small IO
# ---------------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_upload_bytes(raw: bytes) -> str:
    try:
        text = bytes(raw).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateError(f"upload is not valid UTF-8: {exc}") from exc
    if text.startswith("\ufeff"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def load_env_file(path: Path) -> dict[str, str]:
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise GateError(f"env file is not readable: {path}: {exc}") from exc
    values: dict[str, str] = {}
    for raw in raw_lines:
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


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot read JSON {path}: {exc}") from exc


def run(
    cmd: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(cmd), cwd=cwd, env=env, text=True, capture_output=True
    )
    if check and result.returncode != 0:
        raise GateError(
            f"command failed ({result.returncode}): {' '.join(cmd)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def candidate_commit(repo: Path) -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        raise GateError(f"cannot determine candidate commit: {exc}") from exc
    return {"commit": commit, "git_clean": not dirty}


# ---------------------------------------------------------------------------
# Source pack handling (shared by every round's gates)
# ---------------------------------------------------------------------------


def load_source_pack(pack_path: Path, corpus_root: Path) -> dict[str, Any]:
    try:
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot read source pack {pack_path}: {exc}") from exc
    if not isinstance(pack, dict):
        raise GateError(f"source pack must be a JSON object: {pack_path}")
    if pack.get("schema") != "chronicle.corpus-source-pack":
        raise GateError(
            f"source pack schema must be chronicle.corpus-source-pack, "
            f"got {pack.get('schema')!r}"
        )
    works = pack.get("works")
    if not isinstance(works, list) or not works:
        raise GateError("source pack carries no works/uploads")
    uploads: list[dict[str, Any]] = []
    for work in works:
        if not isinstance(work, dict):
            raise GateError("source pack work entry must be an object")
        upload_rel = work.get("upload")
        if not isinstance(upload_rel, str) or not upload_rel:
            raise GateError("source pack work entry is missing its upload path")
        upload_path = (corpus_root / upload_rel).resolve()
        try:
            raw = upload_path.read_bytes()
        except OSError as exc:
            raise GateError(f"upload file is missing: {upload_path}: {exc}") from exc
        text = normalize_upload_bytes(raw)
        uploads.append(
            {
                "work": work.get("work"),
                "upload": upload_rel,
                "path": str(upload_path),
                "sha256": sha256_bytes(raw),
                "bytes": len(raw),
                "chars": len(text),
                "text": text,
            }
        )
    return {"pack": pack, "uploads": uploads}


def verify_pack_manifest_hashes(
    pack: dict[str, Any], uploads: list[dict[str, Any]], corpus_root: Path
) -> dict[str, Any]:
    """Cross-check upload hashes against the frozen ingest manifest."""
    manifest_path = corpus_root / "ingest-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot read ingest manifest {manifest_path}: {exc}") from exc
    expected = {
        str(item.get("ingest_file")): str(item.get("sha256"))
        for item in manifest.get("uploads", [])
        if isinstance(item, dict)
    }
    checked: list[dict[str, Any]] = []
    for upload in uploads:
        want = expected.get(upload["upload"])
        if want is None:
            raise GateError(
                f"upload {upload['upload']!r} is not registered in "
                "ingest-manifest.json; refusing unregistered sources"
            )
        if want != upload["sha256"]:
            raise GateError(
                f"upload {upload['upload']!r} hash drift: manifest {want} "
                f"vs actual {upload['sha256']}"
            )
        checked.append(
            {
                "upload": upload["upload"],
                "sha256": upload["sha256"],
                "bytes": upload["bytes"],
                "chars": upload["chars"],
            }
        )
    return {
        "manifest": "ingest-manifest.json",
        "pack_id": pack.get("pack_id"),
        "uploads": checked,
    }


# ---------------------------------------------------------------------------
# HTTP + Studio helpers
# ---------------------------------------------------------------------------


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
        raise GateError(
            f"expected JSON object, got HTTP {status}: {type(payload).__name__}"
        )
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
    idle_timeout_seconds: int | None = None,
    progress_path: Path | None = None,
) -> dict[str, Any]:
    """Wait within absolute and optional durable-progress deadlines.

    Heartbeats, status timestamps and repeated output IDs are not progress.
    Only newly completed stages/chunks or committed outputs renew idle time;
    no progress can extend the absolute deadline or satisfy ``wanted``.
    """
    if timeout_seconds <= 0 or (
        idle_timeout_seconds is not None and idle_timeout_seconds <= 0
    ):
        raise ValueError("job wait limits must be positive")
    started = time.monotonic()
    deadline = started + timeout_seconds
    last_progress = started
    last_logged = started - 30
    seen: set[tuple[str, str]] = set()
    last: dict[str, Any] = {}
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if idle_timeout_seconds is not None:
            idle_remaining = last_progress + idle_timeout_seconds - time.monotonic()
            if idle_remaining <= 0:
                raise GateError(
                    f"job made no durable progress for {idle_timeout_seconds}s; "
                    f"wanted={sorted(wanted)} last={last}"
                )
            remaining = min(remaining, idle_remaining)
        status, payload = json_http(
            base_url,
            f"/api/v1/studio/jobs/{job_id}",
            auth=auth,
            timeout=min(30, remaining),
        )
        require_status(status, 200, payload, "job detail")
        last = payload["job"]
        now = time.monotonic()
        if now >= deadline:
            break
        progress = {
            ("stage", stage["stage"])
            for stage in last.get("stages", [])
            if stage.get("status") in {"completed", "skipped"}
        } | {
            ("chunk", chunk["chunk_id"])
            for chunk in last.get("chunks", [])
            if chunk.get("status") == "completed"
        } | {
            ("output", output["output_id"])
            for output in last.get("outputs", [])
        }
        changed = bool(progress - seen)
        if changed:
            seen.update(progress)
            last_progress = now
        if progress_path is not None and (
            changed
            or now - last_logged >= 30
            or last.get("status") in wanted | TERMINAL_JOB_STATES
        ):
            observation = {
                "observed_at_unix": time.time(),
                "job_id": job_id,
                "status": last.get("status"),
                "elapsed_seconds": round(now - started, 1),
                "idle_seconds": round(now - last_progress, 1),
                "stages": {s["stage"]: s["status"] for s in last.get("stages", [])},
                "outputs": len(last.get("outputs", [])),
                "open_reviews": last.get("open_reviews"),
            }
            with progress_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(observation, ensure_ascii=False) + "\n")
            last_logged = now
        if last.get("status") in wanted:
            return last
        if (
            last.get("status") in TERMINAL_JOB_STATES
            and last.get("status") not in wanted
        ):
            raise GateError(f"job entered unexpected terminal state: {last}")
        remaining = deadline - time.monotonic()
        if idle_timeout_seconds is not None:
            remaining = min(
                remaining, last_progress + idle_timeout_seconds - time.monotonic()
            )
        time.sleep(max(0, min(2, remaining)))
    raise GateError(
        f"job exceeded absolute wait limit {timeout_seconds}s; "
        f"did not reach {sorted(wanted)}; last={last}"
    )


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


def reviews_for_job(
    base_url: str, auth: str, job_id: str, status_filter: str
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(1000):
        query = (
            f"/api/v1/studio/jobs/reviews?status={status_filter}"
            f"&job_id={job_id}&limit=100"
        )
        if cursor:
            query += f"&cursor={urllib.parse.quote(cursor, safe='')}"
        status, payload = json_http(base_url, query, auth=auth)
        require_status(status, 200, payload, "review list")
        if payload.get("schema") != "chronicle.studio-review-page":
            raise GateError(
                f"unexpected review list schema: {payload.get('schema')!r}"
            )
        collected.extend(payload.get("items", []))
        cursor = payload.get("next_cursor")
        if not cursor:
            break
    else:
        raise GateError("review list pagination did not terminate")
    return [item for item in collected if item.get("job_id") == job_id]


# ---------------------------------------------------------------------------
# Provider configuration guards
# ---------------------------------------------------------------------------


def require_live_config(config: dict[str, str]) -> None:
    """Validate the shared live provider identity used by both rounds."""
    if config.get("CHRONICLE_MODEL_FIXTURE_PACK", "").strip():
        raise GateError(
            "live gate refuses CHRONICLE_MODEL_FIXTURE_PACK; live provider is required"
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


# ---------------------------------------------------------------------------
# Isolated PostgreSQL lifecycle (repository PG18 control service)
# ---------------------------------------------------------------------------


class IsolatedDatabase:
    """Create/drop one isolated Chronicle database on the test control service.

    The control service is the repository-managed PG18 service documented in
    ``docs/development/postgres-tests.md``. The gate applies the product
    migrations and then talks to the database only through product acceptance
    entries; it never inserts semantic rows with raw SQL.
    """

    def __init__(self, control_url: str, *, name: str | None = None) -> None:
        self.control_url = control_url
        self.name = name or f"chronicle_gate_{os.urandom(8).hex()}"
        self.database_url: str | None = None

    def _psycopg(self) -> Any:
        try:
            import psycopg  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise GateError(
                "psycopg is required for the isolated database lifecycle; "
                "install apps/chronicle/persistence/requirements.txt"
            ) from exc
        return psycopg

    def create(self) -> str:
        psycopg = self._psycopg()
        from psycopg import sql  # noqa: PLC0415

        root = Path(__file__).resolve().parents[3]
        persistence = root / "apps" / "chronicle" / "persistence"
        if str(persistence) not in os.sys.path:
            os.sys.path.insert(0, str(persistence))
        from migrations import apply_migrations  # noqa: PLC0415

        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.name))
            )
        from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: PLC0415

        params = conninfo_to_dict(self.control_url)
        params["dbname"] = self.name
        self.database_url = make_conninfo(**params)
        with psycopg.connect(self.database_url) as conn:
            apply_migrations(conn)
        return self.database_url

    def drop(self) -> None:
        psycopg = self._psycopg()
        from psycopg import sql  # noqa: PLC0415

        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(self.name)
                )
            )

    def __enter__(self) -> "IsolatedDatabase":
        self.create()
        return self

    def __exit__(self, *_exc: Any) -> None:
        try:
            self.drop()
        except Exception:  # noqa: BLE001 - cleanup must never mask the failure
            pass


# ---------------------------------------------------------------------------
# Isolated Docker Compose lifecycle
# ---------------------------------------------------------------------------


def default_gate_project(suffix: str) -> str:
    return f"{GATE_PROJECT_PREFIX}-{suffix}-{os.urandom(4).hex()}"


class ComposeStack:
    """Own one isolated Chronicle Compose stack for the duration of a gate run.

    The stack is started on a fresh ``CHRONICLE_DATA_DIR`` and a dedicated
    Compose project so it can never read or mutate an operator's deployment.
    ``down`` removes the project's containers and volumes. This is the single
    stack lifecycle shared by the round gates.
    """

    def __init__(
        self,
        *,
        repo: Path,
        env_file: Path,
        project: str,
        data_dir: Path,
        compose_file: str = "compose.chronicle.yaml",
        base_url: str | None = None,
        worker_lease_seconds: int = 15,
        extra_files: Sequence[str] | None = None,
    ) -> None:
        self.repo = repo
        self.env_file = env_file
        self.project = project
        self.data_dir = data_dir
        self.compose_file = compose_file
        self.base_url = base_url
        self.worker_lease_seconds = worker_lease_seconds
        self.extra_files = list(extra_files or [])
        self.started = False

    def env(self, worker_id: str | None = None) -> dict[str, str]:
        merged = os.environ.copy()
        merged["COMPOSE_PROJECT_NAME"] = self.project
        merged["CHRONICLE_DATA_DIR"] = str(self.data_dir)
        merged["CHRONICLE_WORKER_LEASE_SECONDS"] = str(self.worker_lease_seconds)
        if worker_id:
            merged["CHRONICLE_WORKER_ID"] = worker_id
        return merged

    def _command(self, args: Iterable[str]) -> list[str]:
        cmd = [
            "docker",
            "compose",
            "--env-file",
            str(self.env_file),
            "-f",
            self.compose_file,
        ]
        for extra in self.extra_files:
            cmd += ["-f", extra]
        return [*cmd, *args]

    def compose(
        self,
        args: Iterable[str],
        *,
        worker_id: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return run(self._command(args), cwd=self.repo, env=self.env(worker_id), check=check)

    def compose_run_script(
        self,
        service: str,
        script: str,
        *,
        worker_id: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a Python script inside a one-off service container via stdin.

        The script executes with the image's product modules and the service's
        ``CHRONICLE_DATABASE_URL``; no host filesystem or raw SQL is needed
        for the synthetic tooling.
        """
        result = subprocess.run(
            self._command(["run", "--rm", "-T", service, "python3", "-"]),
            cwd=self.repo,
            env=self.env(worker_id),
            input=script,
            text=True,
            capture_output=True,
        )
        if check and result.returncode != 0:
            raise GateError(
                f"compose run {service} script failed ({result.returncode}):\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    def compose_run(
        self,
        service: str,
        cmd: Sequence[str],
        *,
        worker_id: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a one-off command in a service container (no stdin)."""
        return self.compose(
            ["run", "--rm", "-T", service, *cmd],
            worker_id=worker_id,
            check=check,
        )

    def up(self, *, build: bool = False, profile: str = "worker") -> None:
        args = ["--profile", profile, "up", "-d"]
        if build:
            args.append("--build")
        self.compose(args)
        self.started = True

    def stop_service(self, service: str) -> None:
        self.compose(["--profile", "worker", "stop", service], check=False)

    def start_service(self, service: str) -> None:
        self.compose(["--profile", "worker", "start", service])

    def restart(self, *services: str) -> None:
        self.compose(["--profile", "worker", "restart", *services])

    def exec_(
        self, service: str, cmd: Sequence[str], *, worker_id: str | None = None
    ) -> str:
        return self.compose(
            ["--profile", "worker", "exec", "-T", service, *cmd],
            worker_id=worker_id,
        ).stdout

    def logs(self, service: str, *, worker_id: str | None = None) -> str:
        return self.compose(
            ["--profile", "worker", "logs", "--no-color", service],
            worker_id=worker_id,
        ).stdout

    def ps(self) -> str:
        return self.compose(["--profile", "worker", "ps"]).stdout

    def wait_health(self, timeout_seconds: int = 180) -> None:
        if self.base_url is None:
            raise GateError("ComposeStack has no base_url for a health check")
        wait_health(self.base_url, timeout_seconds)

    def down(self, *, volumes: bool = True) -> None:
        args = ["--profile", "worker", "down"]
        if volumes:
            args.append("-v")
        try:
            self.compose(args, check=False)
        finally:
            self.started = False

    def require_docker(self) -> None:
        if shutil.which("docker") is None:
            raise GateError("docker binary is required for the stack lifecycle")

    def __enter__(self) -> "ComposeStack":
        self.require_docker()
        self.up()
        return self

    def __exit__(self, *_exc: Any) -> None:
        if self.started:
            self.down()


# ---------------------------------------------------------------------------
# Evidence bundle
# ---------------------------------------------------------------------------


class Evidence:
    """Checkpointed evidence bundle for one gate run.

    Writes ``manifest.partial.json`` after every checkpoint and a final
    ``manifest.json`` on success. On failure the caller records ``FAIL`` and
    the partial manifest is preserved for inspection.
    """

    def __init__(self, directory: Path, initial: dict[str, Any]) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.data = dict(initial)
        self.partial_path = self.directory / "manifest.partial.json"
        self.manifest_path = self.directory / "manifest.json"

    def checkpoint(self) -> None:
        write_json(self.partial_path, self.data)

    def finish(self, result: str = "PASS") -> dict[str, Any]:
        self.data["result"] = result
        write_json(self.manifest_path, self.data)
        if self.partial_path.exists():
            self.partial_path.unlink()
        return self.data

    def fail(self, reason: str) -> dict[str, Any]:
        self.data["result"] = "FAIL"
        self.data["failure"] = reason
        write_json(self.partial_path, self.data)
        return self.data
