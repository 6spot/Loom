#!/usr/bin/env python3
"""Strict operator-run C1-T17 production acceptance gate.

All Chronicle mutations use the authenticated Studio HTTP boundary; container
lifecycle uses production Docker Compose; PostgreSQL access is read-only via the
existing corpus metrics command. The gate refuses fixture mode and records a
secret-free evidence bundle for Issue #506.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

import _gate_support as S

GATE_LEASE_SECONDS = 15
WORKER_A = "c1-t17-worker-a"
WORKER_B = "c1-t17-worker-b"


def require_strict_live_config(config: dict[str, str]) -> None:
    S.require_live_config(config)
    parsed = urllib.parse.urlparse(config["CHRONICLE_MODEL_ENDPOINT"])
    if parsed.username is not None or parsed.password is not None:
        raise S.GateError("CHRONICLE_MODEL_ENDPOINT must not embed credentials")


def compose_env(worker_id: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["CHRONICLE_WORKER_LEASE_SECONDS"] = str(GATE_LEASE_SECONDS)
    if worker_id:
        env["CHRONICLE_WORKER_ID"] = worker_id
    return env


def compose(repo: Path, env_file: Path, args: list[str], *, worker_id: str | None = None, check: bool = True):
    return S.run(
        ["docker", "compose", "--env-file", str(env_file), "-f", "compose.chronicle.yaml", *args],
        cwd=repo,
        env=compose_env(worker_id),
        check=check,
    )


def collect_compose(repo: Path, env_file: Path, output: Path, args: list[str], *, worker_id: str | None = None) -> str:
    result = compose(repo, env_file, args, worker_id=worker_id, check=False)
    rendered = result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")
    output.write_text(rendered, encoding="utf-8")
    if result.returncode != 0:
        raise S.GateError(f"docker compose {' '.join(args)} failed; see {output}")
    return result.stdout


def compose_json(repo: Path, env_file: Path, args: list[str], *, worker_id: str | None = None) -> dict[str, Any]:
    result = compose(repo, env_file, args, worker_id=worker_id)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise S.GateError(f"expected JSON from docker compose command: {result.stdout[:500]!r}") from exc


def job_detail(base_url: str, auth: str, job_id: str) -> dict[str, Any]:
    status, payload = S.json_http(base_url, f"/api/v1/studio/jobs/{job_id}", auth=auth)
    S.require_status(status, 200, payload, "job detail")
    return payload["job"]


def wait_lease(base_url: str, auth: str, job_id: str, owner: str, timeout_seconds: int = 180) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = job_detail(base_url, auth, job_id)
        if last.get("lease_owner") == owner:
            return last
        if last.get("status") in S.TERMINAL_JOB_STATES | {"needs_review"}:
            raise S.GateError(f"job advanced to {last.get('status')} before lease owner {owner!r} was observed")
        time.sleep(1)
    raise S.GateError(f"worker lease owner {owner!r} was not observed; last={last}")


def wait_attempt_increment(base_url: str, auth: str, job_id: str, previous: int, timeout_seconds: int = 180) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = job_detail(base_url, auth, job_id)
        if int(last.get("attempt") or 0) > previous:
            return last
        time.sleep(1)
    raise S.GateError(f"worker-B takeover did not increment durable job attempt; last={last}")


def reviews_for_job(base_url: str, auth: str, job_id: str, status_filter: str) -> list[dict[str, Any]]:
    status, payload = S.json_http(
        base_url,
        f"/api/v1/studio/jobs/reviews?status={status_filter}&limit=200",
        auth=auth,
    )
    S.require_status(status, 200, payload, "review list")
    return [item for item in payload.get("reviews", []) if item.get("job_id") == job_id]


def require_operator_review(base_url: str, auth: str, job_id: str, evidence: dict[str, Any]) -> None:
    open_items = reviews_for_job(base_url, auth, job_id, "open")
    if not open_items:
        raise S.GateError("job needs_review but no open resolution ReviewItems were exposed")
    evidence["review_gate"] = {
        "required": True,
        "open_before_operator": [
            {
                "review_id": item.get("review_id"),
                "link_kind": item.get("link_kind"),
                "candidate_id": item.get("candidate_id"),
                "allowed_decisions": item.get("allowed_decisions"),
            }
            for item in open_items
        ],
    }
    print("\nC1-T17 requires human resolution review.")
    print(f"Open Studio at: {base_url.rstrip('/')}/studio/review")
    print(f"Resolve every ReviewItem for job {job_id} from the actual source evidence.")
    if not sys.stdin.isatty():
        raise S.GateError("human Studio Review is required, but stdin is not interactive")
    input("After resolving this job's reviews in Studio, press Enter to continue: ")
    remaining = reviews_for_job(base_url, auth, job_id, "open")
    if remaining:
        raise S.GateError(f"{len(remaining)} ReviewItems for this job remain open")
    all_items = reviews_for_job(base_url, auth, job_id, "all")
    evidence["review_gate"]["decisions"] = [
        {
            "review_id": item.get("review_id"),
            "status": item.get("status"),
            "link_kind": item.get("link_kind"),
            "candidate_id": item.get("candidate_id"),
            "decision": item.get("decision"),
        }
        for item in all_items
    ]


def assert_source_not_seen(base_url: str, auth: str, source_sha256: str) -> None:
    status, payload = S.json_http(base_url, "/api/v1/studio/documents", auth=auth)
    S.require_status(status, 200, payload, "document list")
    for document in payload.get("documents", []):
        document_id = document.get("document_id")
        if not document_id:
            continue
        r_status, revisions = S.json_http(base_url, f"/api/v1/studio/documents/{document_id}/revisions", auth=auth)
        S.require_status(r_status, 200, revisions, "revision history")
        for revision in revisions.get("revisions", []):
            if revision.get("source_sha256") == source_sha256:
                raise S.GateError(
                    "revision-1 SHA-256 already exists in Chronicle; use a fresh previously-unprocessed source "
                    "or reset the dedicated final-gate data directory"
                )


def moment(base_url: str, year: int) -> dict[str, Any]:
    status, payload = S.json_http(base_url, f"/api/v1/public/historical-moment?year={year}&limit=100")
    S.require_status(status, 200, payload, "historical moment")
    return payload


def moment_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "catalog_sha256": payload.get("catalog", {}).get("artifact_sha256"),
        "event_count": len(payload.get("events", [])),
        "entity_count": len(payload.get("entities", [])),
        "place_count": len(payload.get("places", [])),
        "polity_count": len(payload.get("polities", [])),
        "event_ids": sorted(
            str(item.get("canonical_event_id"))
            for item in payload.get("events", [])
            if item.get("canonical_event_id")
        ),
        "coverage": payload.get("coverage"),
    }


def select_changed_event(base_url: str, before: dict[str, Any], after: dict[str, Any], source_text: str) -> dict[str, Any]:
    before_map = {
        str(item.get("canonical_event_id")): (
            int(item.get("source_count") or 0),
            int(item.get("representation_count") or 0),
            len(item.get("claims") or []),
        )
        for item in before.get("events", [])
        if item.get("canonical_event_id")
    }
    candidates: list[tuple[dict[str, Any], bool]] = []
    for event in after.get("events", []):
        event_id = str(event.get("canonical_event_id") or "")
        if not event_id:
            continue
        after_counts = (
            int(event.get("source_count") or 0),
            int(event.get("representation_count") or 0),
            len(event.get("claims") or []),
        )
        before_counts = before_map.get(event_id)
        if before_counts is None or after_counts > before_counts:
            candidates.append((event, before_counts is not None))

    for event, canonical_id_reused in candidates:
        event_id = str(event["canonical_event_id"])
        status, detail = S.json_http(
            base_url,
            f"/api/v1/public/events/{urllib.parse.quote(event_id, safe='')}",
        )
        S.require_status(status, 200, detail, "changed Event detail")
        evidence_text = None
        for representation in detail.get("representations", []):
            for claim in representation.get("claims", []):
                text = claim.get("claim", {}).get("evidence", {}).get("text")
                if isinstance(text, str) and text and text in source_text:
                    evidence_text = text
                    break
            if evidence_text:
                break
        related = [*detail.get("participants", []), *detail.get("places", [])]
        entity = next((item for item in related if item.get("canonical_entity_id")), None)
        presentation = detail.get("reader_presentation")
        matching_support = None
        if isinstance(presentation, dict):
            for block in presentation.get("blocks", []):
                for support in block.get("supports", []):
                    support_text = support.get("claim", {}).get("evidence", {}).get("text")
                    if isinstance(support_text, str) and support_text and support_text in source_text:
                        matching_support = support
                        break
                if matching_support:
                    break
        if (
            evidence_text
            and entity
            and matching_support
            and isinstance(presentation, dict)
            and presentation.get("language") == "zh-CN"
            and event.get("display", {}).get("title")
        ):
            blocks = list(presentation.get("blocks", []))
            presentation_chars = sum(len(str(block.get("text") or "")) for block in blocks)
            if not blocks or presentation_chars < 1:
                continue
            return {
                "event_id": event_id,
                "event_title": event.get("display", {}).get("title"),
                "entity_id": str(entity["canonical_entity_id"]),
                "entity_name": entity.get("display", {}).get("name"),
                "canonical_id_reused": canonical_id_reused,
                "evidence_sha256": S.sha256_bytes(evidence_text.encode("utf-8")),
                "evidence_chars": len(evidence_text),
                "evidence_matches_revision_1": True,
                "presentation_id": presentation.get("presentation_id"),
                "presentation_content_sha256": presentation.get("content_sha256"),
                "presentation_language": presentation.get("language"),
                "presentation_blocks": len(blocks),
                "presentation_text_chars": presentation_chars,
                "presentation_support": {
                    "bundle": matching_support.get("bundle"),
                    "claim_ref": matching_support.get("ref"),
                    "source": matching_support.get("source"),
                },
            }
    raise S.GateError(
        "no newly published/enriched Event in the selected year had exact revision-1 evidence, "
        "a canonical Entity/Place drill-down, and Reader Presentation support from a revision-1 Claim"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env.chronicle")
    parser.add_argument("--source", required=True)
    parser.add_argument("--replacement", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--world-year", required=True, type=int)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--evidence-dir", default="apps/chronicle/.artifacts/c1-t17")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[3]

    def resolve(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else (repo / path).resolve()

    env_file = resolve(args.env_file)
    source = resolve(args.source)
    replacement = resolve(args.replacement)
    evidence_dir = resolve(args.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    if not env_file.is_file():
        raise S.GateError(f"env file not found: {env_file}")
    for path in (source, replacement):
        if not path.is_file() or path.suffix.lower() not in {".txt", ".md"}:
            raise S.GateError(f"source must be an existing .txt/.md file: {path}")
        path.read_text(encoding="utf-8")
    if source.read_bytes() == replacement.read_bytes():
        raise S.GateError("replacement must differ from revision 1")

    file_config = S.load_env_file(env_file)
    config = dict(file_config)
    config.update({k: v for k, v in os.environ.items() if k.startswith("CHRONICLE_")})
    require_strict_live_config(config)
    base_url = args.base_url or f"http://127.0.0.1:{config.get('CHRONICLE_PORT', '8080')}"
    auth = S.basic_auth(config["CHRONICLE_ADMIN_USER"], config["CHRONICLE_ADMIN_PASSWORD"])

    commit = S.run(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
    if S.run(["git", "status", "--porcelain"], cwd=repo).stdout.strip():
        raise S.GateError("C1-T17 must run from a clean exact candidate checkout")
    if platform.system().lower() != "linux":
        raise S.GateError("C1-T17 production gate must run on Debian/Linux")
    os_release_path = Path("/etc/os-release")
    os_release = os_release_path.read_text(encoding="utf-8") if os_release_path.exists() else ""
    if "debian" not in os_release.lower():
        raise S.GateError("C1-T17 production gate must run on Debian")

    evidence: dict[str, Any] = {
        "schema": "chronicle.c1-t17-evidence",
        "version": "0.2",
        "candidate": {"commit": commit, "git_clean": True},
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "platform": platform.platform(),
            "os_release_sha256": S.sha256_bytes(os_release.encode("utf-8")),
        },
        "provider": S.safe_provider(config),
        "source": {
            "first": {
                "filename": source.name,
                "sha256": S.sha256_bytes(source.read_bytes()),
                "bytes": source.stat().st_size,
            },
            "replacement": {
                "filename": replacement.name,
                "sha256": S.sha256_bytes(replacement.read_bytes()),
                "bytes": replacement.stat().st_size,
            },
        },
        "world_year": args.world_year,
        "worker_gate": {
            "lease_seconds": GATE_LEASE_SECONDS,
            "worker_a": WORKER_A,
            "worker_b": WORKER_B,
        },
    }
    S.write_json(evidence_dir / "manifest.partial.json", evidence)
    (evidence_dir / "os-release.txt").write_text(os_release, encoding="utf-8")

    evidence["docker"] = {
        "engine": S.run(["docker", "--version"], cwd=repo).stdout.strip(),
        "compose": S.run(["docker", "compose", "version"], cwd=repo).stdout.strip(),
    }
    up_args = ["--profile", "worker", "up", "-d"]
    if not args.skip_build:
        up_args.append("--build")
    collect_compose(repo, env_file, evidence_dir / "compose-up.txt", up_args, worker_id=WORKER_A)
    S.wait_health(base_url)
    collect_compose(repo, env_file, evidence_dir / "compose-ps.txt", ["--profile", "worker", "ps"], worker_id=WORKER_A)
    collect_compose(repo, env_file, evidence_dir / "compose-images.txt", ["--profile", "worker", "images"], worker_id=WORKER_A)

    pg = compose(
        repo,
        env_file,
        ["exec", "-T", "postgres", "sh", "-ec", 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SHOW server_version"'],
        worker_id=WORKER_A,
    ).stdout.strip()
    evidence["postgresql"] = {"server_version": pg}
    if not pg.startswith("18"):
        raise S.GateError(f"C1-T17 requires PostgreSQL 18, got {pg!r}")

    unauth_status, unauth_payload = S.json_http(base_url, "/api/v1/studio/status")
    if unauth_status != 401:
        raise S.GateError(
            f"Studio unauthenticated status must fail closed with 401, got {unauth_status}: {unauth_payload}"
        )
    auth_status, auth_payload = S.json_http(base_url, "/api/v1/studio/status", auth=auth)
    S.require_status(auth_status, 200, auth_payload, "authenticated Studio status")
    if auth_payload.get("admin_user") != config["CHRONICLE_ADMIN_USER"]:
        raise S.GateError("authenticated Studio status returned unexpected admin user")
    evidence["studio_auth"] = {
        "unauthenticated_status": unauth_status,
        "authenticated_status": auth_status,
        "admin_user": auth_payload.get("admin_user"),
        "upstream": auth_payload.get("upstream"),
    }

    assert_source_not_seen(base_url, auth, S.sha256_bytes(source.read_bytes()))
    before = moment(base_url, args.world_year)
    evidence["before_world"] = moment_summary(before)
    evidence["before_metrics"] = compose_json(
        repo,
        env_file,
        ["--profile", "worker", "exec", "-T", "chronicle-worker", "python3", "apps/chronicle/corpus/metrics.py"],
        worker_id=WORKER_A,
    )

    c0_browser = S.run(
        [sys.executable, "apps/chronicle/web/browser_smoke.py", "--base-url", base_url],
        cwd=repo,
    )
    c0_output = c0_browser.stdout + c0_browser.stderr
    (evidence_dir / "c0-browser-regression.txt").write_text(c0_output, encoding="utf-8")
    evidence["c0_browser_regression"] = {
        "passed": True,
        "output_sha256": S.sha256_bytes(c0_output.encode("utf-8")),
    }

    # Stop the long-lived worker before the Job exists. This makes the
    # fault-injection worker the only process that can claim the queued Job,
    # so the retry proof is deterministic rather than a race with worker-A.
    collect_compose(
        repo,
        env_file,
        evidence_dir / "worker-stop-before-queue.txt",
        ["--profile", "worker", "stop", "chronicle-worker"],
        worker_id=WORKER_A,
    )

    create_body = json.dumps({"title": args.title}, ensure_ascii=False).encode("utf-8")
    status, payload = S.json_http(
        base_url,
        "/api/v1/studio/documents",
        method="POST",
        body=create_body,
        content_type="application/json",
        auth=auth,
    )
    S.require_status(status, 201, payload, "create document")
    document_id = payload["document"]["document_id"]
    rev1 = S.upload_revision(base_url, auth, document_id, source, "c1-t17-live")
    evidence["document"] = {"document_id": document_id, "revision_1": rev1}
    job = S.queue_job(base_url, auth, rev1["revision_id"])
    job_id = job["job_id"]
    evidence["job_id"] = job_id

    fault = collect_compose(
        repo,
        env_file,
        evidence_dir / "worker-fault-injection.txt",
        [
            "--profile", "worker", "run", "--rm", "chronicle-worker",
            "python3", "apps/chronicle/worker/ingestion_worker.py",
            "--worker-id", "c1-t17-retry-proof",
            "--lease-seconds", str(GATE_LEASE_SECONDS),
            "--max-jobs", "1",
            "--fail-stage", "prepare:1",
        ],
        worker_id=WORKER_A,
    )
    failed = S.wait_job(base_url, auth, job_id, wanted={"failed"}, timeout_seconds=120)
    evidence["retry_proof"] = {
        "failed_job": failed,
        "fault_log_sha256": S.sha256_bytes(fault.encode("utf-8")),
    }
    S.job_action(base_url, auth, job_id, "retry")
    collect_compose(
        repo,
        env_file,
        evidence_dir / "worker-start-after-retry.txt",
        ["--profile", "worker", "start", "chronicle-worker"],
        worker_id=WORKER_A,
    )

    pre_kill = wait_lease(base_url, auth, job_id, WORKER_A)
    pre_attempt = int(pre_kill.get("attempt") or 0)
    evidence["restart_resume"] = {
        "pre_kill_status": pre_kill.get("status"),
        "pre_kill_attempt": pre_attempt,
        "pre_kill_lease_owner": pre_kill.get("lease_owner"),
        "forced_kill": True,
        "lease_wait_seconds": GATE_LEASE_SECONDS + 5,
    }
    collect_compose(
        repo,
        env_file,
        evidence_dir / "worker-a-before-kill.log",
        ["--profile", "worker", "logs", "--no-color", "chronicle-worker"],
        worker_id=WORKER_A,
    )
    collect_compose(
        repo,
        env_file,
        evidence_dir / "worker-kill.txt",
        ["--profile", "worker", "kill", "-s", "KILL", "chronicle-worker"],
        worker_id=WORKER_A,
    )
    time.sleep(GATE_LEASE_SECONDS + 5)
    collect_compose(
        repo,
        env_file,
        evidence_dir / "worker-b-recreate.txt",
        ["--profile", "worker", "up", "-d", "--force-recreate", "chronicle-worker"],
        worker_id=WORKER_B,
    )
    takeover = wait_attempt_increment(base_url, auth, job_id, pre_attempt)
    evidence["restart_resume"].update(
        {
            "takeover_attempt": int(takeover.get("attempt") or 0),
            "takeover_status": takeover.get("status"),
            "takeover_lease_owner_observed": takeover.get("lease_owner"),
        }
    )

    current = S.wait_job(
        base_url,
        auth,
        job_id,
        wanted={"needs_review", "completed"},
        timeout_seconds=1800,
    )
    if current.get("status") == "needs_review":
        require_operator_review(base_url, auth, job_id, evidence)
        S.job_action(base_url, auth, job_id, "resume")
        current = S.wait_job(base_url, auth, job_id, wanted={"completed"}, timeout_seconds=1800)
    else:
        evidence["review_gate"] = {
            "required": False,
            "reason": "no blocking resolution candidates",
        }
    evidence["completed_job"] = current
    collect_compose(
        repo,
        env_file,
        evidence_dir / "worker-b-final.log",
        ["--profile", "worker", "logs", "--no-color", "chronicle-worker"],
        worker_id=WORKER_B,
    )

    rev2 = S.upload_revision(base_url, auth, document_id, replacement, "c1-t17-live-replacement")
    if rev2.get("revision_no") != 2 or rev2.get("supersedes_revision_id") != rev1.get("revision_id"):
        raise S.GateError(f"replacement did not create auditable revision-2 supersession: {rev2}")
    old_status, old_bytes, _ = S.http(
        base_url,
        f"/api/v1/studio/documents/{document_id}/revisions/1/content",
        auth=auth,
    )
    if old_status != 200 or old_bytes != source.read_bytes():
        raise S.GateError("revision 1 content is no longer auditable after replacement")
    evidence["document"]["revision_2"] = rev2
    evidence["document"]["revision_1_still_exact"] = True

    after = moment(base_url, args.world_year)
    evidence["after_world"] = moment_summary(after)
    evidence["after_metrics"] = compose_json(
        repo,
        env_file,
        ["--profile", "worker", "exec", "-T", "chronicle-worker", "python3", "apps/chronicle/corpus/metrics.py"],
        worker_id=WORKER_B,
    )
    if evidence["after_world"]["catalog_sha256"] == evidence["before_world"]["catalog_sha256"]:
        raise S.GateError("canonical catalog did not change after live ingestion")
    before_ids = set(evidence["before_world"]["event_ids"])
    after_ids = set(evidence["after_world"]["event_ids"])
    missing_ids = sorted(before_ids - after_ids)
    if missing_ids:
        raise S.GateError(
            f"canonical Event IDs disappeared from selected-year projection after publication: {missing_ids}"
        )
    evidence["canonical_identity_stability"] = {
        "selected_year_before_event_ids": len(before_ids),
        "selected_year_retained_event_ids": len(before_ids & after_ids),
        "missing_event_ids": missing_ids,
    }

    public_sample = select_changed_event(
        base_url, before, after, source.read_text(encoding="utf-8")
    )
    evidence["new_public_sample"] = public_sample
    browser = S.run(
        [
            sys.executable,
            "apps/chronicle/acceptance/world_browser_smoke.py",
            "--base-url", base_url,
            "--year", str(args.world_year),
            "--event-id", public_sample["event_id"],
        ],
        cwd=repo,
    )
    browser_output = browser.stdout + browser.stderr
    (evidence_dir / "world-browser-smoke.txt").write_text(browser_output, encoding="utf-8")
    evidence["browser_smoke"] = {
        "passed": True,
        "output_sha256": S.sha256_bytes(browser_output.encode("utf-8")),
    }
    collect_compose(
        repo,
        env_file,
        evidence_dir / "compose-final-ps.txt",
        ["--profile", "worker", "ps"],
        worker_id=WORKER_B,
    )

    evidence["result"] = "PASS"
    S.write_json(evidence_dir / "manifest.json", evidence)
    print(f"C1-T17 gate: PASS evidence={evidence_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except S.GateError as exc:
        print(f"C1-T17 gate: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
