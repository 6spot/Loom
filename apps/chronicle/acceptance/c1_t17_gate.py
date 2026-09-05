#!/usr/bin/env python3
"""C1-T17 operator-run production acceptance gate for Chronicle.

This tool is intentionally orchestration-only. It drives the real authenticated
Studio HTTP boundary, Docker Compose, durable worker, and public HTTP surface.
It never writes Chronicle PostgreSQL directly and never enables fixture mode.

The gate records an evidence directory suitable for attaching to #506. Secrets
are never rendered: passwords/API keys are reduced to presence booleans and the
model endpoint is reduced to scheme + host + path.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SCHEMA = "chronicle.c1-t17-evidence"
VERSION = "0.1"
TERMINAL_JOB_STATES = {"completed", "failed", "cancelled"}


class GateError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
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
        values[key.strip()] = value.strip()
    return values


def require_live_config(config: dict[str, str]) -> None:
    if config.get("CHRONICLE_MODEL_FIXTURE_PACK", "").strip():
        raise GateError("C1-T17 refuses CHRONICLE_MODEL_FIXTURE_PACK; live provider is required")
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
        raise GateError(f"missing required live-gate configuration: {', '.join(missing)}")
    parsed = urllib.parse.urlparse(config["CHRONICLE_MODEL_ENDPOINT"])
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise GateError("CHRONICLE_MODEL_ENDPOINT must be an absolute http(s) URL")


def safe_provider(config: dict[str, str]) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(config["CHRONICLE_MODEL_ENDPOINT"])
    return {
        "endpoint": urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", "")),
        "api_key_present": bool(config.get("CHRONICLE_MODEL_API_KEY", "").strip()),
        "extraction_model": config["CHRONICLE_EXTRACTION_MODEL"],
        "presentation_model": config["CHRONICLE_PRESENTATION_MODEL"],
        "timeout_seconds": config.get("CHRONICLE_MODEL_TIMEOUT_SECONDS", "120"),
        "fixture_mode": False,
    }


def basic_auth(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def http(base: str, path: str, *, method: str = "GET", body: bytes | None = None,
         content_type: str | None = None, auth: str | None = None, timeout: float = 30.0) -> tuple[int, bytes, dict[str, str]]:
    headers = {"Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    if auth:
        headers["Authorization"] = auth
    request = urllib.request.Request(base.rstrip("/") + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers.items())


def json_http(*args: Any, **kwargs: Any) -> tuple[int, dict[str, Any]]:
    status, body, _headers = http(*args, **kwargs)
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise GateError(f"expected JSON response, got HTTP {status}: {body[:500]!r}") from exc
    return status, payload


def require_status(status: int, expected: int | tuple[int, ...], payload: Any, label: str) -> None:
    allowed = (expected,) if isinstance(expected, int) else expected
    if status not in allowed:
        raise GateError(f"{label} returned HTTP {status}, expected {allowed}: {payload}")


def wait_health(base_url: str, timeout_seconds: int = 120) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            status, _payload = json_http(base_url, "/healthz", timeout=3)
            if status == 200:
                return
        except Exception:
            pass
        time.sleep(1)
    raise GateError("Chronicle web health check did not become ready")


def wait_job(base_url: str, auth: str, job_id: str, *, wanted: set[str], timeout_seconds: int = 900) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] = {}
    while time.time() < deadline:
        status, payload = json_http(base_url, f"/api/v1/studio/jobs/{job_id}", auth=auth)
        require_status(status, 200, payload, "job detail")
        last = payload["job"]
        if last.get("status") in wanted:
            return last
        if last.get("status") in TERMINAL_JOB_STATES and last.get("status") not in wanted:
            raise GateError(f"job entered unexpected terminal state: {last}")
        time.sleep(2)
    raise GateError(f"job did not reach {sorted(wanted)}; last={last}")


def resolve_open_reviews(base_url: str, auth: str, job_id: str, evidence: dict[str, Any]) -> int:
    status, payload = json_http(base_url, "/api/v1/studio/jobs/reviews?status=open&limit=200", auth=auth)
    require_status(status, 200, payload, "review list")
    resolved = 0
    records: list[dict[str, Any]] = []
    for review in payload.get("reviews", []):
        if review.get("job_id") != job_id:
            continue
        allowed = list(review.get("allowed_decisions") or [])
        if not allowed:
            raise GateError(f"open review {review.get('review_id')} has no allowed decisions")
        # Final gate is not an identity oracle. Prefer the explicit non-merging
        # decision when available; otherwise choose the first legal decision and
        # record it for operator inspection.
        decision = "uncertain" if "uncertain" in allowed else (
            "related_occurrence" if "related_occurrence" in allowed else allowed[0]
        )
        request_body = json.dumps({
            "decision": decision,
            "rationale": "C1-T17 operator acceptance: conservative non-merging decision unless source identity is proven separately.",
            "confidence": 0.5,
        }, ensure_ascii=False).encode("utf-8")
        r_status, r_payload = json_http(
            base_url,
            f"/api/v1/studio/jobs/reviews/{review['review_id']}/decision",
            method="POST",
            body=request_body,
            content_type="application/json",
            auth=auth,
        )
        require_status(r_status, 200, r_payload, "review decision")
        records.append({"review_id": review["review_id"], "decision": decision, "allowed": allowed})
        resolved += 1
    evidence["review_decisions"] = records
    return resolved


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def collect_compose(repo: Path, env_file: Path, output: Path, args: list[str]) -> str:
    cmd = ["docker", "compose", "--env-file", str(env_file), "-f", "compose.chronicle.yaml", *args]
    result = run(cmd, cwd=repo, check=False)
    rendered = result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")
    output.write_text(rendered, encoding="utf-8")
    if result.returncode != 0:
        raise GateError(f"docker compose {' '.join(args)} failed; see {output}")
    return result.stdout


def source_query(filename: str, source_label: str) -> str:
    return urllib.parse.urlencode({"filename": filename, "language": "zh-CN", "source_label": source_label})


def upload_revision(base_url: str, auth: str, document_id: str, source: Path, source_label: str) -> dict[str, Any]:
    raw = source.read_bytes()
    status, payload = json_http(
        base_url,
        f"/api/v1/studio/documents/{document_id}/revisions?{source_query(source.name, source_label)}",
        method="POST",
        body=raw,
        content_type="text/markdown" if source.suffix.lower() == ".md" else "text/plain",
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
    status, payload = json_http(base_url, "/api/v1/studio/jobs", method="POST", body=body,
                                content_type="application/json", auth=auth)
    require_status(status, 201, payload, "queue job")
    return payload["job"]


def job_action(base_url: str, auth: str, job_id: str, action: str) -> dict[str, Any]:
    status, payload = json_http(base_url, f"/api/v1/studio/jobs/{job_id}/{action}", method="POST",
                                body=b"{}", content_type="application/json", auth=auth)
    require_status(status, 200, payload, f"job {action}")
    return payload["job"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env.chronicle")
    parser.add_argument("--source", required=True, help="previously unprocessed complete UTF-8 .txt/.md source")
    parser.add_argument("--replacement", required=True, help="controlled changed revision of the same document")
    parser.add_argument("--title", required=True)
    parser.add_argument("--world-year", required=True, type=int)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--evidence-dir", default="apps/chronicle/.artifacts/c1-t17")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[3]
    env_file = (repo / args.env_file).resolve() if not Path(args.env_file).is_absolute() else Path(args.env_file)
    source = (repo / args.source).resolve() if not Path(args.source).is_absolute() else Path(args.source)
    replacement = (repo / args.replacement).resolve() if not Path(args.replacement).is_absolute() else Path(args.replacement)
    evidence_dir = (repo / args.evidence_dir).resolve() if not Path(args.evidence_dir).is_absolute() else Path(args.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    if not env_file.is_file():
        raise GateError(f"env file not found: {env_file}")
    for path in (source, replacement):
        if not path.is_file() or path.suffix.lower() not in {".txt", ".md"}:
            raise GateError(f"source must be an existing .txt/.md file: {path}")
        path.read_text(encoding="utf-8")
    if source.read_bytes() == replacement.read_bytes():
        raise GateError("replacement must differ from the first revision")

    file_config = load_env_file(env_file)
    config = dict(file_config)
    config.update({k: v for k, v in os.environ.items() if k.startswith("CHRONICLE_")})
    require_live_config(config)

    base_url = args.base_url or f"http://127.0.0.1:{config.get('CHRONICLE_PORT', '8080')}"
    auth = basic_auth(config["CHRONICLE_ADMIN_USER"], config["CHRONICLE_ADMIN_PASSWORD"])
    commit = run(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
    status = run(["git", "status", "--porcelain"], cwd=repo).stdout
    if status.strip():
        raise GateError("C1-T17 must run from a clean exact candidate checkout")

    evidence: dict[str, Any] = {
        "schema": SCHEMA,
        "version": VERSION,
        "candidate": {"commit": commit, "git_clean": True},
        "host": {"system": platform.system(), "release": platform.release(), "platform": platform.platform()},
        "provider": safe_provider(config),
        "source": {
            "first": {"filename": source.name, "sha256": sha256_bytes(source.read_bytes()), "bytes": source.stat().st_size},
            "replacement": {"filename": replacement.name, "sha256": sha256_bytes(replacement.read_bytes()), "bytes": replacement.stat().st_size},
        },
        "world_year": args.world_year,
    }
    write_json(evidence_dir / "manifest.partial.json", evidence)

    run(["docker", "--version"], cwd=repo).stdout.strip()
    evidence["docker"] = {
        "engine": run(["docker", "--version"], cwd=repo).stdout.strip(),
        "compose": run(["docker", "compose", "version"], cwd=repo).stdout.strip(),
    }
    if platform.system().lower() != "linux":
        raise GateError("C1-T17 production gate must run on Debian/Linux")
    os_release = Path("/etc/os-release").read_text(encoding="utf-8") if Path("/etc/os-release").exists() else ""
    if "debian" not in os_release.lower():
        raise GateError("C1-T17 production gate must run on Debian")
    evidence["host"]["os_release_sha256"] = sha256_bytes(os_release.encode("utf-8"))

    up_args = ["--profile", "worker", "up", "-d"]
    if not args.skip_build:
        up_args.append("--build")
    collect_compose(repo, env_file, evidence_dir / "compose-up.txt", up_args)
    wait_health(base_url)
    collect_compose(repo, env_file, evidence_dir / "compose-ps.txt", ["--profile", "worker", "ps"])

    before_status, before = json_http(base_url, f"/api/v1/public/historical-moment?year={args.world_year}&limit=100")
    require_status(before_status, 200, before, "before historical moment")
    evidence["before_world"] = {
        "catalog_sha256": before.get("catalog", {}).get("artifact_sha256"),
        "event_count": len(before.get("events", [])),
        "entity_count": len(before.get("entities", [])),
        "coverage": before.get("coverage"),
    }

    create_body = json.dumps({"title": args.title}, ensure_ascii=False).encode("utf-8")
    status, payload = json_http(base_url, "/api/v1/studio/documents", method="POST", body=create_body,
                                content_type="application/json", auth=auth)
    require_status(status, 201, payload, "create document")
    document_id = payload["document"]["document_id"]
    rev1 = upload_revision(base_url, auth, document_id, source, "c1-t17-live")
    evidence["document"] = {"document_id": document_id, "revision_1": rev1}
    job = queue_job(base_url, auth, rev1["revision_id"])
    job_id = job["job_id"]
    evidence["job_id"] = job_id

    # Deterministic retry proof on real uploaded source: stop the normal worker,
    # run one real-source worker process with a scripted prepare failure, then
    # invoke the product retry API and restart the production worker.
    collect_compose(repo, env_file, evidence_dir / "worker-stop-before-retry.txt", ["--profile", "worker", "stop", "chronicle-worker"])
    fault = collect_compose(
        repo,
        env_file,
        evidence_dir / "worker-fault-injection.txt",
        ["--profile", "worker", "run", "--rm", "chronicle-worker", "python3", "apps/chronicle/worker/ingestion_worker.py",
         "--worker-id", "c1-t17-retry-proof", "--lease-seconds", "15", "--max-jobs", "1", "--fail-stage", "prepare:1"],
    )
    failed = wait_job(base_url, auth, job_id, wanted={"failed"}, timeout_seconds=120)
    evidence["retry_proof"] = {"failed_job_attempt": failed.get("attempt"), "fault_log_sha256": sha256_bytes(fault.encode("utf-8"))}
    job_action(base_url, auth, job_id, "retry")
    collect_compose(repo, env_file, evidence_dir / "worker-start-after-retry.txt", ["--profile", "worker", "start", "chronicle-worker"])

    # Wait until real work has begun, then kill the worker hard. After the 15s
    # gate lease expires a fresh worker must reclaim the durable running job.
    running = wait_job(base_url, auth, job_id, wanted={"running", "needs_review", "completed"}, timeout_seconds=180)
    if running.get("status") == "running":
        collect_compose(repo, env_file, evidence_dir / "worker-kill.txt", ["--profile", "worker", "kill", "-s", "KILL", "chronicle-worker"])
        time.sleep(20)
        collect_compose(repo, env_file, evidence_dir / "worker-restart.txt", ["--profile", "worker", "up", "-d", "chronicle-worker"])
        evidence["restart_resume"] = {"forced_kill": True, "lease_wait_seconds": 20}
    else:
        evidence["restart_resume"] = {"forced_kill": False, "reason": f"job advanced to {running.get('status')} before kill window"}

    current = wait_job(base_url, auth, job_id, wanted={"needs_review", "completed"}, timeout_seconds=1800)
    if current.get("status") == "needs_review":
        resolved = resolve_open_reviews(base_url, auth, job_id, evidence)
        if resolved == 0:
            raise GateError("job needs_review but no resolution reviews were exposed")
        job_action(base_url, auth, job_id, "resume")
        current = wait_job(base_url, auth, job_id, wanted={"completed"}, timeout_seconds=1800)
    evidence["completed_job"] = current

    # Verify revision replacement through the same authenticated upload API.
    rev2 = upload_revision(base_url, auth, document_id, replacement, "c1-t17-live-replacement")
    if rev2.get("revision_no") != 2 or rev2.get("supersedes_revision_id") != rev1.get("revision_id"):
        raise GateError(f"replacement did not create an auditable revision 2 supersession: {rev2}")
    old_status, old_bytes, _ = http(base_url, f"/api/v1/studio/documents/{document_id}/revisions/1/content", auth=auth)
    if old_status != 200 or old_bytes != source.read_bytes():
        raise GateError("revision 1 content is no longer auditable after replacement")
    evidence["document"]["revision_2"] = rev2
    evidence["document"]["revision_1_still_exact"] = True

    after_status, after = json_http(base_url, f"/api/v1/public/historical-moment?year={args.world_year}&limit=100")
    require_status(after_status, 200, after, "after historical moment")
    evidence["after_world"] = {
        "catalog_sha256": after.get("catalog", {}).get("artifact_sha256"),
        "event_count": len(after.get("events", [])),
        "entity_count": len(after.get("entities", [])),
        "coverage": after.get("coverage"),
    }
    if evidence["after_world"]["catalog_sha256"] == evidence["before_world"]["catalog_sha256"]:
        raise GateError("canonical catalog did not change after live ingestion")

    # Reuse the committed production-front browser contract for World -> Event
    # -> Entity -> evidence. It uses only public HTTP plus a real headless Chrome.
    browser = run([
        sys.executable,
        "apps/chronicle/web/world_browser_smoke.py",
        "--base-url", base_url,
        "--year", str(args.world_year),
    ], cwd=repo)
    (evidence_dir / "world-browser-smoke.txt").write_text(browser.stdout + browser.stderr, encoding="utf-8")
    evidence["browser_smoke"] = {"passed": True, "output_sha256": sha256_bytes((browser.stdout + browser.stderr).encode("utf-8"))}

    collect_compose(repo, env_file, evidence_dir / "compose-final-ps.txt", ["--profile", "worker", "ps"])
    collect_compose(repo, env_file, evidence_dir / "worker-final.log", ["--profile", "worker", "logs", "--no-color", "chronicle-worker"])
    evidence["result"] = "PASS"
    write_json(evidence_dir / "manifest.json", evidence)
    print(f"C1-T17 gate: PASS evidence={evidence_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GateError as exc:
        print(f"C1-T17 gate: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
