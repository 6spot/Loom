#!/usr/bin/env python3
"""Chronicle second-round continuous-reading automated gate (C2-R2-T16).

Unified thin orchestration entry for the second-round acceptance loop::

    python3 apps/chronicle/acceptance/second_round_gate.py \
        --mode fixture \
        --env-file /tmp/chronicle-second-round-test.env \
        --source-pack apps/chronicle/corpus/first-round/source-pack.json \
        --evidence-dir /tmp/chronicle-r2-offline

``fixture`` mode runs the real deployed stack through the shared
``gate_runtime`` lifecycle: an isolated Docker Compose project (PostgreSQL 18,
Rust ``chronicle-server`` front, Python ``read_api`` sidecar, durable worker)
plus an in-gate deterministic 0.2 model provider served over HTTP. The gate
uploads the frozen sources through the authenticated Studio HTTP boundary,
queues jobs, lets the real worker publish, reads the result through the public
Rust HTTP reading routes, injects fail-closed faults, restarts the stack, seeds
the explicitly synthetic 5,000-unit/1,000-group scale stream, and finally runs
the real-browser ``reading-flow-smoke.mjs`` suite against the running front.
No product row is written with raw SQL by this module (the synthetic scale
fixture is a separately labelled module).

``live`` mode performs the strict prechecks for a real-provider run and stops
with a READY handoff for T17; it never calls a real provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

GATE_SCHEMA = "chronicle.second-round-gate-evidence"
GATE_VERSION = "0.2"
BROWSER_MANIFEST_SCHEMA = "chronicle.reading-flow-fixture"
BROWSER_MANIFEST_VERSION = "0.2"
FIXTURE_DISCLAIMER = (
    "fixture mode is deterministic offline orchestration only; "
    "it is NOT live content proof and MUST NOT be cited as real "
    "translation/reading-annotation correctness evidence"
)
VIEWPORTS = (
    {"name": "desktop-1440", "width": 1440, "height": 900},
    {"name": "tablet-1024", "width": 1024, "height": 768},
    {"name": "mobile-390", "width": 390, "height": 844},
    {"name": "narrow-320", "width": 320, "height": 568},
)
PERF_BUDGETS = {
    "active_to_sidebar_p95_ms": 100,
    "restore_p95_ms": 250,
    "max_long_task_ms": 200,
    # reading-experience.md §3: at most 120 rendered units, plus up to 20
    # pinned units under focus/selection/expanded-reference, so 140 is the
    # absolute mounted-window ceiling.
    "mounted_max_units": 140,
    "target_units": 5000,
    "target_groups": 1000,
}

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PERSISTENCE_DIR = REPO / "apps" / "chronicle" / "persistence"
WORKER_DIR = REPO / "apps" / "chronicle" / "worker"
READ_API_DIR = REPO / "apps" / "chronicle" / "read_api"
for _path in (str(HERE), str(PERSISTENCE_DIR), str(WORKER_DIR), str(READ_API_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from gate_runtime import (  # noqa: E402
    ComposeStack,
    Evidence,
    GateError,
    basic_auth,
    candidate_commit,
    default_gate_project,
    json_http,
    load_env_file,
    load_source_pack,
    queue_job,
    require_live_config,
    require_status,
    reviews_for_job,
    safe_provider,
    upload_revision,
    verify_pack_manifest_hashes,
    wait_health,
    wait_job,
    write_json,
)
from reading_scale_fixture import (  # noqa: E402
    SCALE_GROUPS_PLACEHOLDER,
    SCALE_UNITS_PLACEHOLDER,
    SEED_SCRIPT,
    parse_scale_result,
)

import chapter_contract  # noqa: E402
import fixture_model  # noqa: E402
import reading_contract  # noqa: E402


# ---------------------------------------------------------------------------
# Boundary guards
# ---------------------------------------------------------------------------


def check_no_direct_product_writes() -> dict[str, Any]:
    """Prove this orchestrator never writes product rows with raw SQL.

    Product mutation must go through the deployed stack's public HTTP or the
    product acceptance entries. Raw INSERT/UPDATE/DELETE/CREATE/DROP/ALTER
    statements are refused here.
    """
    lines = Path(__file__).read_text(encoding="utf-8").splitlines()
    scanning = True
    code_lines: list[str] = []
    for line in lines:
        if line.startswith("def check_no_direct_product_writes"):
            scanning = False
            continue
        if not scanning and line.startswith("def ") and "(" in line:
            scanning = True
        if scanning:
            code_lines.append(line)
    text = "\n".join(code_lines)
    forbidden = (
        "INSERT INTO",
        "UPDATE chronicle.",
        "DELETE FROM",
        "CREATE TABLE",
        "DROP TABLE",
        "ALTER TABLE",
    )
    hits = sorted({token for token in forbidden if token in text})
    if hits:
        raise GateError(
            "second_round_gate.py must not write product tables directly; "
            f"forbidden tokens present: {hits}"
        )
    return {"direct_product_writes": False, "checked_tokens": len(forbidden)}


def require_fixture_env(config: dict[str, str]) -> None:
    """Fixture mode never calls a real live provider."""
    if config.get("CHRONICLE_MODEL_FIXTURE_PACK", "").strip():
        raise GateError(
            "fixture mode refuses CHRONICLE_MODEL_FIXTURE_PACK; the gate's own "
            "HTTP fixture provider is the only fixture source"
        )
    if config.get("CHRONICLE_CHAPTER_FIXTURE_PACK", "").strip():
        raise GateError(
            "fixture mode refuses CHRONICLE_CHAPTER_FIXTURE_PACK; the gate's "
            "own HTTP fixture provider is the only fixture source"
        )


def require_live_env(config: dict[str, str]) -> dict[str, Any]:
    """Strict live-provider preflight for current staged chapter production."""
    if config.get("CHRONICLE_CHAPTER_FIXTURE_PACK", "").strip():
        raise GateError(
            "live mode refuses CHRONICLE_CHAPTER_FIXTURE_PACK; fixture "
            "material must never enter a live run"
        )
    require_live_config(config)
    if not config.get("CHRONICLE_CHAPTER_MODEL", "").strip():
        raise GateError(
            "missing required live configuration: CHRONICLE_CHAPTER_MODEL"
        )
    if config["CHRONICLE_CHAPTER_MODEL"].strip().startswith("fixture:"):
        raise GateError("live mode refuses the frozen fixture chapter model entry")
    parsed = urllib.parse.urlparse(config["CHRONICLE_MODEL_ENDPOINT"])
    if parsed.username is not None or parsed.password is not None:
        raise GateError("CHRONICLE_MODEL_ENDPOINT must not embed credentials")
    provider = safe_provider(config)
    provider["chapter_model"] = config["CHRONICLE_CHAPTER_MODEL"]
    provider["candidate_version"] = chapter_contract.PRODUCTION_CANDIDATE_VERSION
    return provider


# ---------------------------------------------------------------------------
# Deterministic 0.2 fixture provider served over the real provider protocol
# ---------------------------------------------------------------------------


def pick_unique_mention(text: str, blocked: set[str]) -> str:
    for length in (6, 8, 10, 12):
        step = max(1, length // 2)
        for start in range(0, max(0, len(text) - length), step):
            snippet = text[start : start + length]
            if not snippet.strip() or "\n" in snippet or "#" in snippet:
                continue
            if snippet in blocked:
                continue
            if text.count(snippet) == 1:
                return snippet
    raise GateError("no unique verbatim mention found in chapter text")


def grounded_spec(request: dict[str, Any], source_title: str) -> dict[str, Any]:
    text = request["normalized_text"]
    mention = pick_unique_mention(text, set())
    return {
        "chapter_id": request["chapter_id"],
        "revision_id": request["revision_id"],
        "source_title": source_title,
        "translation_text": f"fixture白話譯文（{mention}）非真實譯文",
        "entities": [{"mention": mention, "type": "person", "name": mention}],
        "event": {"type": "battle", "title": f"fixture事件（{mention}）"},
        "predicate": "affected",
    }


def add_resolved_span(candidate: dict[str, Any], request: dict[str, Any]) -> None:
    """Attach one resolved event span so the browser can exercise previews.

    The deterministic fixture builder leaves spans empty; the acceptance gate
    adds a single grounded span (selection quote present in the translation
    block, source selection present in the chapter blocks) so event
    preview/targets are reachable on the real stack. The owning T01 validator
    still rejects anything ungrounded.
    """
    units = candidate.get("reading", {}).get("units", [])
    blocks = candidate.get("translation", {}).get("blocks", [])
    events = candidate.get("bundle", {}).get("events", [])
    mentions = candidate.get("mentions", [])
    if not units or not events or not mentions:
        return
    event_ref = events[0]["temp_id"]
    mention = str(mentions[0].get("surface") or "")
    if not mention:
        return
    for unit in units:
        block = next(
            (item for item in blocks if item.get("block_id") == unit.get("block_id")),
            None,
        )
        if block is None or mention not in block.get("text", ""):
            continue
        selection = fixture_model._chapter_selection_for(
            quote=mention,
            text=request["normalized_text"],
            blocks=request["blocks"],
            owner="gate reading span",
        )
        unit["event_spans"] = [
            {
                "span_id": "es_001",
                "selection": {"quote": mention, "occurrence": 1},
                "status": "resolved",
                "target_ref": event_ref,
                "candidate_refs": [],
                "relation": "current",
                "source_selections": [selection],
            }
        ]
        unit["current_event_refs"] = [event_ref]
        return


def fixture_candidate(prompt: str) -> str:
    request = fixture_model._chapter_request_from_t05_prompt(prompt)
    candidate = fixture_model.build_reading_chapter_candidate(
        request, grounded_spec(request, "gate-fixture")
    )
    add_resolved_span(candidate, request)
    return json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))


class FixtureModelProvider:
    """The in-gate HTTP provider implementing the Responses-style protocol."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.calls = 0
        #: When set, any prompt containing this token receives a malformed
        #: candidate so the gate can inject a deterministic mid-chain failure.
        self.fail_token: str | None = None

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                try:
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                    prompt = str(body.get("input", ""))
                    if provider.fail_token and provider.fail_token in prompt:
                        text = '{"broken": true}'
                    else:
                        text = fixture_candidate(prompt)
                    provider.calls += 1
                    payload = {
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "content": [{"type": "output_text", "text": text}],
                            }
                        ],
                    }
                    self._respond(200, payload)
                except Exception as exc:  # noqa: BLE001 - fail closed over HTTP
                    self._respond(
                        500,
                        {"status": "failed", "error": {"message": str(exc)[:500]}},
                    )

            def _respond(self, status: int, payload: dict[str, Any]) -> None:
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        return Handler

    def start(self) -> None:
        self.server = ThreadingHTTPServer(("0.0.0.0", self.port), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# ---------------------------------------------------------------------------
# Stack environment + lifecycle
# ---------------------------------------------------------------------------


def write_stack_env(
    source_env: Path, out: Path, *, endpoint: str, web_port: int
) -> Path:
    config = load_env_file(source_env)
    config.setdefault("CHRONICLE_POSTGRES_USER", "chronicle")
    config.setdefault("CHRONICLE_POSTGRES_DB", "chronicle")
    config["CHRONICLE_PORT"] = str(web_port)
    config["CHRONICLE_BIND_IP"] = "127.0.0.1"
    config["CHRONICLE_MODEL_ENDPOINT"] = endpoint
    # Explicitly select the worker's frozen fixture entry. A reading-chapter
    # suffix alone must not downgrade a live model from staged production.
    config["CHRONICLE_CHAPTER_MODEL"] = (
        "fixture:gate-r2:" + fixture_model.READING_CHAPTER_MODEL_SUFFIX
    )
    config["CHRONICLE_MODEL_TIMEOUT_SECONDS"] = config.get(
        "CHRONICLE_MODEL_TIMEOUT_SECONDS", "180"
    )
    for key in ("CHRONICLE_MODEL_FIXTURE_PACK", "CHRONICLE_CHAPTER_FIXTURE_PACK"):
        config.pop(key, None)
    out.write_text(
        "".join(f"{key}={value}\n" for key, value in sorted(config.items())),
        encoding="utf-8",
    )
    return out


def write_worker_override(path: Path) -> Path:
    path.write_text(
        "services:\n"
        "  chronicle-worker:\n"
        "    extra_hosts:\n"
        '      - "host.docker.internal:host-gateway"\n',
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Studio HTTP boundary
# ---------------------------------------------------------------------------


def create_document(base_url: str, auth: str, title: str) -> dict[str, Any]:
    body = json.dumps({"title": title}, ensure_ascii=False).encode("utf-8")
    status, payload = json_http(
        base_url,
        "/api/v1/studio/documents",
        method="POST",
        body=body,
        content_type="application/json",
        auth=auth,
    )
    require_status(status, 201, payload, "create document")
    return payload["document"]


def resolve_open_reviews(
    base_url: str, auth: str, job_id: str, evidence: dict[str, Any]
) -> None:
    open_items = reviews_for_job(base_url, auth, job_id, "open")
    if not open_items:
        return
    resolved = []
    for item in open_items:
        allowed = list(item.get("allowed_decisions") or [])
        decision = "same" if "same" in allowed else (allowed[0] if allowed else "uncertain")
        status, payload = json_http(
            base_url,
            f"/api/v1/studio/jobs/reviews/{item['review_id']}/decision",
            method="POST",
            body=json.dumps(
                {
                    "decision": decision,
                    "rationale": "fixture mode fixed decision",
                    "confidence": 1.0,
                }
            ).encode("utf-8"),
            content_type="application/json",
            auth=auth,
        )
        require_status(status, 200, payload, "review decision")
        resolved.append({"review_id": item["review_id"], "decision": decision})
    evidence.setdefault("review_decisions", []).extend(resolved)


def publish_upload(
    base_url: str, auth: str, upload: dict[str, Any], evidence: dict[str, Any]
) -> dict[str, Any]:
    document = create_document(
        base_url, auth, upload["work"] or Path(upload["upload"]).name
    )
    published = publish_revision(
        base_url, auth, document["document_id"], Path(upload["path"]), "c2r2-gate", evidence
    )
    published["upload"] = upload["upload"]
    return published


def publish_revision(
    base_url: str,
    auth: str,
    document_id: str,
    source: Path,
    source_label: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    revision = upload_revision(base_url, auth, document_id, source, source_label)
    job = queue_job(base_url, auth, revision["revision_id"])
    current = wait_job(
        base_url,
        auth,
        job["job_id"],
        wanted={"completed", "needs_review"},
        timeout_seconds=1800,
        idle_timeout_seconds=600,
    )
    if current.get("status") == "needs_review":
        resolve_open_reviews(base_url, auth, job["job_id"], evidence)
        job_action = json_http(
            base_url,
            f"/api/v1/studio/jobs/{job['job_id']}/resume",
            method="POST",
            body=b"{}",
            content_type="application/json",
            auth=auth,
        )
        require_status(job_action[0], 200, job_action[1], "job resume")
        current = wait_job(
            base_url,
            auth,
            job["job_id"],
            wanted={"completed"},
            timeout_seconds=1800,
            idle_timeout_seconds=600,
        )
    if current.get("status") != "completed":
        raise GateError(f"job {job['job_id']} did not complete: {current.get('status')}")
    return {
        "document_id": document_id,
        "revision_id": revision["revision_id"],
        "job_id": job["job_id"],
    }


# ---------------------------------------------------------------------------
# Public HTTP reads
# ---------------------------------------------------------------------------


def public_json(base_url: str, path: str, *, timeout_seconds: int = 60) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while True:
        status, payload = json_http(base_url, path)
        if status == 200:
            return payload
        if status in (502, 503) and time.time() < deadline:
            time.sleep(1)
            continue
        raise GateError(f"{path} returned HTTP {status}: {payload}")


def collect_stream(
    base_url: str, revision_id: str, catalog_sha: str
) -> dict[str, Any]:
    directory = public_json(base_url, f"/api/v1/public/reading-streams?catalog={catalog_sha}")
    items = directory["page"]["streams"]
    match = next(
        (item for item in items if item.get("revision_id") == revision_id), None
    )
    if match is None:
        raise GateError(
            f"published revision {revision_id} is missing from the public directory"
        )
    stream_id = match["stream_id"]
    result: dict[str, Any] = {
        "stream_id": stream_id,
        "catalog_sha": catalog_sha,
        "revision_id": revision_id,
        "unit_count": int(match["unit_count"]),
        "group_count": int(match["group_count"]),
        "directory": directory,
    }
    result["detail"] = public_json(
        base_url, f"/api/v1/public/reading-streams/{stream_id}?catalog={catalog_sha}"
    )
    units = public_json(
        base_url,
        f"/api/v1/public/reading-streams/{stream_id}/units?catalog={catalog_sha}&limit=50",
    )
    result["units"] = units
    result["groups"] = public_json(
        base_url,
        f"/api/v1/public/reading-streams/{stream_id}/groups?catalog={catalog_sha}&limit=100",
    )
    first = units["page"]["units"][0]
    result["first_unit_id"] = first["unit_id"]
    result["locate"] = public_json(
        base_url,
        f"/api/v1/public/reading-streams/{stream_id}/locate"
        f"?catalog={catalog_sha}&unit_id={first['unit_id']}&limit=5",
    )
    event_ids = _event_ids_from_units(units["page"]["units"])
    result["event_ids"] = event_ids
    if event_ids:
        result["event_preview"] = public_json(
            base_url,
            f"/api/v1/public/reading-events/{event_ids[0]}/preview?catalog={catalog_sha}",
        )
        result["event_targets"] = public_json(
            base_url,
            f"/api/v1/public/reading-events/{event_ids[0]}/targets?catalog={catalog_sha}&limit=20",
        )
    _assert_units_reassemble(base_url, result)
    _assert_negative_locator(base_url, result)
    return result


def _event_ids_from_units(units: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for unit in units:
        for segment in unit.get("segments", []):
            if segment.get("kind") != "event":
                continue
            span = segment.get("span") or {}
            event_id = span.get("target_event_id")
            if event_id and event_id not in seen:
                seen.add(event_id)
                found.append(event_id)
    return found


def assert_time_contract(narrative_time: dict[str, Any]) -> None:
    """Assert a narrative_time is contract-complete, not just schema-valid.

    JSON Schema cannot express that an ``events``/``mixed`` time must carry at
    least one event reference while ``unknown``/``inherit`` must not. The
    product DTO validator therefore accepts the inconsistent shape; the gate
    rejects it here so a synthetic or mis-generated unit can never be treated
    as contract evidence.
    """
    mode = narrative_time.get("mode")
    refs = narrative_time.get("event_refs")
    if not isinstance(refs, list):
        raise GateError("narrative_time.event_refs must be an array")
    if mode in ("events", "mixed") and not refs:
        raise GateError(f"narrative_time mode {mode!r} requires event_refs")
    if mode in ("unknown", "inherit") and refs:
        raise GateError(f"narrative_time mode {mode!r} must not carry event_refs")
    for field in (
        "status",
        "from_block_id",
        "observations",
        "year_key",
        "period_key",
        "year_label",
        "period_label",
        "precision",
        "continues_previous",
    ):
        if field not in narrative_time:
            raise GateError(f"narrative_time missing {field!r}")


def validate_scale_contract(base_url: str, scale: dict[str, Any]) -> dict[str, Any]:
    """Validate the synthetic scale stream's DTOs and time/role contract."""
    units = public_json(
        base_url,
        f"/api/v1/public/reading-streams/{scale['stream_id']}/units"
        f"?catalog={scale['catalog_sha']}&limit=50",
    )["page"]["units"]
    groups = public_json(
        base_url,
        f"/api/v1/public/reading-streams/{scale['stream_id']}/groups"
        f"?catalog={scale['catalog_sha']}&limit=50",
    )["page"]["groups"]
    if not units or not groups:
        raise GateError("synthetic scale stream exposed no units or groups")
    for unit in units:
        errors = reading_contract.validate_reading_dto("reading_unit", unit)
        if errors:
            raise GateError(f"synthetic unit DTO invalid: {errors}")
        assert_time_contract(unit["narrative_time"])
        for entity in unit.get("context_entities", []):
            entity_errors = reading_contract.validate_reading_dto(
                "context_entity_view", entity
            )
            if entity_errors:
                raise GateError(f"synthetic context entity DTO invalid: {entity_errors}")
    for group in groups:
        errors = reading_contract.validate_reading_dto("time_group", group)
        if errors:
            raise GateError(f"synthetic time group DTO invalid: {errors}")
    return {
        "units_checked": len(units),
        "groups_checked": len(groups),
        "narrative_modes": sorted({unit["narrative_time"]["mode"] for unit in units}),
        "context_entities": sum(len(unit.get("context_entities", [])) for unit in units),
    }


def find_negatives(base_url: str, scale: dict[str, Any]) -> list[dict[str, Any]]:
    """Locate the explicit unknown-time / missing-context / missing-role units."""
    units = public_json(
        base_url,
        f"/api/v1/public/reading-streams/{scale['stream_id']}/units"
        f"?catalog={scale['catalog_sha']}&limit=50",
    )["page"]["units"]
    negatives: dict[str, dict[str, Any]] = {}
    for index, unit in enumerate(units):
        if "unknown_time" not in negatives and unit["narrative_time"]["mode"] == "unknown":
            negatives["unknown_time"] = {
                "kind": "unknown_time",
                "stream_id": scale["stream_id"],
                "catalog_sha": scale["catalog_sha"],
                "unit_id": unit["unit_id"],
            }
        if (
            "missing_context" not in negatives
            and not unit.get("context_entities")
            and index > 0
            and units[index - 1].get("context_entities")
        ):
            negatives["missing_context"] = {
                "kind": "missing_context",
                "stream_id": scale["stream_id"],
                "catalog_sha": scale["catalog_sha"],
                "unit_id": unit["unit_id"],
                "previous_context_unit_id": units[index - 1]["unit_id"],
            }
        for entity in unit.get("context_entities", []):
            if "missing_role" not in negatives and not entity.get("event_roles"):
                negatives["missing_role"] = {
                    "kind": "missing_role",
                    "stream_id": scale["stream_id"],
                    "catalog_sha": scale["catalog_sha"],
                    "unit_id": unit["unit_id"],
                    "entity_ref": entity["entity_ref"],
                }
                break
    for kind in ("unknown_time", "missing_context", "missing_role"):
        if kind not in negatives:
            raise GateError(f"fixture data exposes no {kind!r} negative scenario")
    return [negatives[kind] for kind in ("unknown_time", "missing_context", "missing_role")]



def _assert_units_reassemble(base_url: str, result: dict[str, Any]) -> None:
    units = result["units"]["page"]["units"]
    if not units:
        raise GateError("published stream exposed no units")
    for unit in units:
        joined = "".join(
            segment.get("text", "")
            for segment in unit.get("segments", [])
            if "text" in segment
        )
        if not joined:
            raise GateError(f"unit {unit.get('unit_id')} rendered no text")
    if result["locate"]["page"]["units"][0]["unit_id"] != result["first_unit_id"]:
        raise GateError("public locate did not return the exact requested unit")
    page = result["detail"].get("page")
    if not isinstance(page, dict) or page.get("chapters") is None:
        raise GateError("stream detail carries no chapter directory")


def _unknown_uuid7() -> uuid.UUID:
    raw = bytearray(uuid.uuid4().bytes)
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(raw))


def _assert_negative_locator(base_url: str, result: dict[str, Any]) -> None:
    status, payload = json_http(
        base_url,
        f"/api/v1/public/reading-streams/{result['stream_id']}/locate"
        f"?catalog={result['catalog_sha']}&unit_id=ru_{'0' * 24}&limit=5",
    )
    if status != 404:
        raise GateError(f"unknown locator must fail closed with 404, got {status}: {payload}")
    result["unknown_locator_status"] = status
    status, payload = json_http(
        base_url, f"/api/v1/public/reading-streams/{_unknown_uuid7()}"
    )
    if status != 404:
        raise GateError(f"unknown stream must fail closed with 404, got {status}: {payload}")
    result["unknown_stream_status"] = status


# ---------------------------------------------------------------------------
# Fault injection on the real stack
# ---------------------------------------------------------------------------


def fault_checks(
    stack: ComposeStack,
    base_url: str,
    auth: str,
    upload: dict[str, Any],
    *,
    provider: FixtureModelProvider,
    evidence_dir: Path,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    faults: dict[str, Any] = {}
    before = public_json(base_url, "/api/v1/public/reading-streams")
    before_ids = [item["stream_id"] for item in before["page"]["streams"]]

    # F1: a deterministic mid-chain model failure leaves no public half-product
    # and no readable stream for the failed revision. The production worker's
    # --fail-stage plan only scripts the legacy fake executor, so the gate
    # injects the failure through its own provider instead.
    token = "GATEFAULTTOKEN"
    fault_source = evidence_dir / "fault-source.md"
    fault_source.write_text(
        upload["text"] + f"\n\n{token}\n", encoding="utf-8"
    )
    provider.fail_token = token
    try:
        document = create_document(base_url, auth, "fault-source")
        revision = upload_revision(
            base_url, auth, document["document_id"], fault_source, "c2r2-fault"
        )
        job = queue_job(base_url, auth, revision["revision_id"])
        failed = wait_job(
            base_url, auth, job["job_id"], wanted={"failed"}, timeout_seconds=600
        )
    finally:
        provider.fail_token = None
    after_failed = public_json(base_url, "/api/v1/public/reading-streams")
    after_ids = [item["stream_id"] for item in after_failed["page"]["streams"]]
    if failed.get("status") != "failed":
        raise GateError("injected chain failure did not fail the job")
    if [item for item in after_ids if item not in before_ids]:
        raise GateError("failed chain leaked a public reading stream")
    rev_stream = [
        item
        for item in after_failed["page"]["streams"]
        if item.get("revision_id") == revision["revision_id"]
    ]
    if rev_stream:
        raise GateError("failed revision became publicly readable")
    faults["chain_failure_no_partial"] = {
        "passed": True,
        "job_status": "failed",
        "error": (failed.get("error") or "")[:200],
    }

    # F2: restart/redeploy keeps the published stream readable.
    stack.restart("chronicle-web", "chronicle-read")
    wait_health(base_url, timeout_seconds=180)
    after_restart = public_json(base_url, "/api/v1/public/reading-streams")
    restart_ids = [item["stream_id"] for item in after_restart["page"]["streams"]]
    if restart_ids != before_ids:
        raise GateError(
            f"public streams changed across restart: {before_ids} -> {restart_ids}"
        )
    faults["restart_preserves_streams"] = {"passed": True, "streams": len(restart_ids)}

    # F3: unknown snapshot and unknown locator fail closed via public HTTP.
    bad_catalog, _ = json_http(
        base_url, f"/api/v1/public/reading-streams?catalog={'0' * 64}"
    )
    faults["unknown_snapshot_refused"] = {
        "passed": bad_catalog in (400, 404),
        "status": bad_catalog,
    }
    if bad_catalog not in (400, 404):
        raise GateError(f"unknown catalog must fail closed, got {bad_catalog}")

    # F4: role/time contract negatives. The product schema cannot reject an
    # events-mode time with no event reference, so the gate enforces it.
    unknown_time = {
        "mode": "unknown",
        "status": "unknown",
        "event_refs": [],
        "from_block_id": None,
        "observations": [],
        "year_key": "unknown",
        "period_key": "unknown",
        "year_label": None,
        "period_label": "时间未明确",
        "precision": "unknown",
        "continues_previous": False,
    }
    assert_time_contract(unknown_time)
    faults["unknown_time_contract"] = {"passed": True}
    try:
        assert_time_contract({**unknown_time, "mode": "events", "status": "resolved"})
    except GateError as exc:
        faults["events_without_refs_rejected"] = {"passed": True, "error": str(exc)[:160]}
    else:
        raise GateError("events-mode time without event_refs must be rejected")
    entity = {
        "entity_ref": "scale_ent_1",
        "name": "合成人物",
        "canonical_id": None,
        "kind": "person",
        "importance": "primary",
        "source_anchor_ids": [],
        "event_roles": [],
    }
    entity_errors = reading_contract.validate_reading_dto("context_entity_view", entity)
    if entity_errors:
        raise GateError(f"context entity without role must be DTO-valid: {entity_errors}")
    faults["context_role_optional"] = {"passed": True}

    evidence["faults"] = faults
    return faults


# ---------------------------------------------------------------------------
# Synthetic scale fixture
# ---------------------------------------------------------------------------


def seed_scale_stream(
    stack: ComposeStack, *, units: int, groups: int
) -> dict[str, Any]:
    script = SEED_SCRIPT.replace(SCALE_UNITS_PLACEHOLDER, str(units)).replace(
        SCALE_GROUPS_PLACEHOLDER, str(groups)
    )
    result = stack.compose_run_script("chronicle-worker", script)
    return parse_scale_result(result.stdout)


# ---------------------------------------------------------------------------
# Browser manifest + driver
# ---------------------------------------------------------------------------


def build_browser_manifest(
    works: list[dict[str, Any]],
    *,
    base_url: str,
    scale: dict[str, Any],
    versions: list[dict[str, Any]],
    negatives: list[dict[str, Any]],
) -> dict[str, Any]:
    streams = [
        {
            "stream_id": work["stream_id"],
            "catalog_sha": work["catalog_sha"],
            "source_title": work.get("source_title"),
            "unit_count": work["unit_count"],
            "group_count": work["group_count"],
            "first_unit_id": work["first_unit_id"],
            "event_ids": work.get("event_ids", []),
        }
        for work in works
    ]
    return {
        "schema": BROWSER_MANIFEST_SCHEMA,
        "version": BROWSER_MANIFEST_VERSION,
        "generated_by": "C2-R2-T16",
        "base_url": base_url,
        "streams": streams,
        "versions": versions,
        "negatives": negatives,
        "scale": {
            "synthetic": True,
            "status": "measured",
            "stream_id": scale["stream_id"],
            "catalog_sha": scale["catalog_sha"],
            "unit_count": scale["unit_count"],
            "group_count": scale["group_count"],
            "first_unit_id": scale["first_unit_id"],
            "last_unit_id": scale["last_unit_id"],
            "target_units": PERF_BUDGETS["target_units"],
            "target_groups": PERF_BUDGETS["target_groups"],
        },
        "viewports": list(VIEWPORTS),
        "budgets": dict(PERF_BUDGETS),
    }


def validate_browser_manifest(manifest: Any) -> dict[str, Any]:
    """Fail closed when the manifest the driver depends on is incomplete."""
    if not isinstance(manifest, dict):
        raise GateError("browser fixture manifest must be a JSON object")
    if manifest.get("schema") != BROWSER_MANIFEST_SCHEMA:
        raise GateError(
            f"browser fixture manifest schema must be {BROWSER_MANIFEST_SCHEMA!r}"
        )
    streams = manifest.get("streams")
    if not isinstance(streams, list) or not streams:
        raise GateError("browser fixture manifest carries no streams")
    for stream in streams:
        for key in ("stream_id", "catalog_sha", "first_unit_id", "unit_count", "group_count"):
            if stream.get(key) in (None, ""):
                raise GateError(f"browser fixture stream missing {key!r}: {stream}")
        if len(str(stream["catalog_sha"])) != 64:
            raise GateError("browser fixture catalog_sha must be 64 hex chars")
    scale = manifest.get("scale")
    if not isinstance(scale, dict) or not scale.get("stream_id"):
        raise GateError("browser fixture manifest carries no synthetic scale stream")
    if int(scale.get("unit_count", 0)) < PERF_BUDGETS["target_units"]:
        raise GateError(
            "synthetic scale stream is below the 5,000-unit target: "
            f"{scale.get('unit_count')}"
        )
    if int(scale.get("group_count", 0)) < PERF_BUDGETS["target_groups"]:
        raise GateError(
            "synthetic scale stream is below the 1,000-group target: "
            f"{scale.get('group_count')}"
        )
    versions = manifest.get("versions")
    if not isinstance(versions, list) or not versions:
        raise GateError("browser fixture manifest carries no content versions")
    negatives = manifest.get("negatives")
    if not isinstance(negatives, list):
        raise GateError("browser fixture manifest carries no negative scenarios")
    kinds = {item.get("kind") for item in negatives if isinstance(item, dict)}
    for required in ("unknown_time", "missing_context", "missing_role"):
        if required not in kinds:
            raise GateError(f"browser fixture manifest missing {required!r} negative")
        for item in negatives:
            if item.get("kind") == required:
                for field in ("stream_id", "catalog_sha", "unit_id"):
                    if not item.get(field):
                        raise GateError(f"negative {required!r} missing {field!r}")
    return manifest


def run_browser_driver(
    manifest_path: Path, *, base_url: str, suite: str, output_dir: Path
) -> dict[str, Any]:
    script = REPO / "apps" / "chronicle" / "webapp" / "scripts" / "reading-flow-smoke.mjs"
    if not script.is_file():
        raise GateError(f"browser driver is missing: {script}")
    if not shutil.which("node"):
        raise GateError("node is required to run the reading browser driver")
    output_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "node",
            str(script),
            "--base-url",
            base_url,
            "--fixture-manifest",
            str(manifest_path),
            "--suite",
            suite,
            "--output",
            str(output_dir),
        ],
        cwd=REPO,
        text=True,
        capture_output=True,
    )
    (output_dir / "driver.log").write_text(
        result.stdout + "\n" + result.stderr, encoding="utf-8"
    )
    payload: Any = None
    payload_path = output_dir / "result.json"
    if payload_path.is_file():
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    if result.returncode != 0:
        raise GateError(
            f"reading-flow-smoke failed ({result.returncode}); see {output_dir}: "
            f"{(result.stdout + result.stderr)[-1000:]}"
        )
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise GateError(f"reading-flow-smoke did not report ok=true: {payload}")
    return payload


# ---------------------------------------------------------------------------
# Fixture mode (real stack)
# ---------------------------------------------------------------------------


def run_fixture(
    env_file: Path,
    pack_path: Path,
    evidence_dir: Path,
    argv: list[str],
    *,
    allow_dirty: bool,
    build: bool,
    run_browser: bool,
    browser_required: bool,
    keep_stack: bool,
) -> dict[str, Any]:
    evidence = Evidence(
        evidence_dir,
        {
            "schema": GATE_SCHEMA,
            "version": GATE_VERSION,
            "mode": "fixture",
            "fixture_only": True,
            "disclaimer": FIXTURE_DISCLAIMER,
            "command": argv,
        },
    )
    stack: ComposeStack | None = None
    provider = FixtureModelProvider(free_port())
    try:
        evidence.data["no_direct_product_writes"] = check_no_direct_product_writes()
        evidence.data["candidate"] = candidate_commit(REPO)
        if not evidence.data["candidate"]["git_clean"] and not allow_dirty:
            raise GateError(
                "fixture gate requires a clean checkout; re-run with "
                "--allow-dirty for local iteration only"
            )
        file_config = load_env_file(env_file)
        require_fixture_env(file_config)
        evidence.data["env"] = {
            "env_file": str(env_file),
            "chronicle_keys": sorted(
                k for k in file_config if k.startswith("CHRONICLE_")
            ),
        }
        corpus_root = pack_path.parent.resolve()
        loaded = load_source_pack(pack_path, corpus_root)
        evidence.data["source"] = verify_pack_manifest_hashes(
            loaded["pack"], loaded["uploads"], corpus_root
        )

        provider.start()
        endpoint = f"http://host.docker.internal:{provider.port}/v1/responses"
        stack_env = write_stack_env(
            env_file, evidence_dir / "stack.env", endpoint=endpoint, web_port=18080
        )
        override = write_worker_override(evidence_dir / "compose.gate.yaml")
        data_dir = evidence_dir / "stack-data"
        data_dir.mkdir(parents=True, exist_ok=True)
        base_url = "http://127.0.0.1:18080"
        stack = ComposeStack(
            repo=REPO,
            env_file=stack_env,
            project=default_gate_project("r2"),
            data_dir=data_dir,
            base_url=base_url,
            worker_lease_seconds=30,
            extra_files=[str(override)],
        )
        stack.up(build=build)
        wait_health(base_url, timeout_seconds=300)
        config = load_env_file(stack_env)
        auth = basic_auth(config["CHRONICLE_ADMIN_USER"], config["CHRONICLE_ADMIN_PASSWORD"])
        evidence.data["stack"] = {
            "project": stack.project,
            "base_url": base_url,
            "fixture_endpoint": endpoint,
            "image_built": build,
        }
        evidence.checkpoint()

        works: list[dict[str, Any]] = []
        published_meta: list[dict[str, Any]] = []
        for upload in loaded["uploads"]:
            published = publish_upload(base_url, auth, upload, evidence.data)
            published_meta.append(published)
            latest = public_json(base_url, "/api/v1/public/reading-streams")
            source_catalog = latest["snapshot"]["catalog_sha"]
            collected = collect_stream(
                base_url, published["revision_id"], source_catalog
            )
            collected["source_title"] = upload["work"] or Path(upload["upload"]).name
            collected["job_id"] = published["job_id"]
            works.append(collected)
            evidence.data["works"] = works
            evidence.checkpoint()

        # Content-version scenario: publish a second revision of the first
        # work so the browser can prove a pinned old reference does not jump
        # to the newest stream.
        version_source = evidence_dir / "version-2.md"
        version_source.write_text(
            loaded["uploads"][0]["text"] + "\n\n版本二新增段落。\n", encoding="utf-8"
        )
        v2 = publish_revision(
            base_url,
            auth,
            published_meta[0]["document_id"],
            version_source,
            "c2r2-v2",
            evidence.data,
        )
        v2_catalog = public_json(
            base_url, "/api/v1/public/reading-streams"
        )["snapshot"]["catalog_sha"]
        v2_stream = collect_stream(base_url, v2["revision_id"], v2_catalog)
        v2_stream["source_title"] = "version-2"
        works.append(v2_stream)
        evidence.data["works"] = works
        versions = [
            {
                "label": "v1",
                "catalog_sha": works[0]["catalog_sha"],
                "stream_id": works[0]["stream_id"],
            },
            {
                "label": "v2",
                "catalog_sha": v2_catalog,
                "stream_id": v2_stream["stream_id"],
            },
        ]
        evidence.checkpoint()

        evidence.data["faults"] = fault_checks(
            stack,
            base_url,
            auth,
            loaded["uploads"][0],
            provider=provider,
            evidence_dir=evidence_dir,
            evidence=evidence.data,
        )
        evidence.checkpoint()

        publication_id = works[0]["units"]["page"]["units"][0]["publication_id"]
        scale = seed_scale_stream(stack, units=5000, groups=1000)
        evidence.data["scale"] = scale
        evidence.data["scale_contract"] = validate_scale_contract(base_url, scale)
        negatives = find_negatives(base_url, scale)
        evidence.data["negatives"] = negatives
        evidence.checkpoint()

        manifest = validate_browser_manifest(
            build_browser_manifest(
                works,
                base_url=base_url,
                scale=scale,
                versions=versions,
                negatives=negatives,
            )
        )
        manifest_path = evidence_dir / "browser-fixture-manifest.json"
        write_json(manifest_path, manifest)
        evidence.data["browser_manifest"] = {
            "path": str(manifest_path),
            "schema": manifest["schema"],
            "streams": len(manifest["streams"]),
            "scale_units": manifest["scale"]["unit_count"],
            "scale_groups": manifest["scale"]["group_count"],
        }

        if run_browser:
            evidence.data["browser"] = run_browser_driver(
                manifest_path,
                base_url=base_url,
                suite="all",
                output_dir=evidence_dir / "browser",
            )
        elif browser_required:
            raise GateError(
                "a browser run was required but --skip-browser was set"
            )
        else:
            evidence.data["browser"] = {
                "ok": False,
                "reason": "browser suite skipped by --skip-browser",
            }

        measured = bool(evidence.data["browser"].get("ok"))
        evidence.data["criteria"] = {
            "real_stack_offline_chain": "PASS",
            "negative_faults": (
                "PASS"
                if all(item.get("passed") for item in evidence.data["faults"].values())
                else "FAIL"
            ),
            "browser_interaction": "PASS" if measured else "NOT_RUN",
            "performance_budget": "PASS" if measured else "NOT_MEASURED",
        }
        if browser_required and not measured:
            raise GateError("browser/performance evidence was required but not produced")
        return evidence.finish("PASS")
    except GateError as exc:
        evidence.fail(str(exc))
        raise
    finally:
        provider.stop()
        if stack is not None and not keep_stack:
            stack.down()


# ---------------------------------------------------------------------------
# Live mode (strict preflight + READY handoff for T17)
# ---------------------------------------------------------------------------


def require_interactive_stdin() -> bool:
    if not sys.stdin.isatty():
        raise GateError(
            "live mode requires an interactive terminal: stdin is not a TTY, "
            "so no operator could resolve blocking reviews in Studio"
        )
    return True


def compose_config_check(env_file: Path) -> dict[str, Any]:
    if shutil.which("docker") is None:
        return {"checked": False, "reason": "docker binary unavailable"}
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            "compose.chronicle.yaml",
            "config",
            "--quiet",
        ],
        cwd=REPO,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise GateError(
            "live compose config failed: " + (result.stdout + result.stderr)[:1000]
        )
    return {"checked": True}


def run_live(
    env_file: Path,
    pack_path: Path,
    evidence_dir: Path,
    argv: list[str],
    *,
    auto_decide: bool,
    non_interactive: bool,
    execute: bool,
) -> dict[str, Any]:
    if auto_decide:
        raise GateError(
            "live mode refuses --auto-decide; identity decisions require review"
        )
    if non_interactive:
        raise GateError(
            "live mode refuses --non-interactive; reviews pause for an operator"
        )
    if execute:
        raise GateError(
            "T16 live execution belongs to T17; this entry issues a READY handoff"
        )
    require_interactive_stdin()
    evidence = Evidence(
        evidence_dir,
        {
            "schema": GATE_SCHEMA,
            "version": GATE_VERSION,
            "mode": "live",
            "fixture_only": False,
            "command": argv,
        },
    )
    try:
        evidence.data["no_direct_product_writes"] = check_no_direct_product_writes()
        evidence.data["candidate"] = candidate_commit(REPO)
        if not evidence.data["candidate"]["git_clean"]:
            raise GateError("live gate requires a clean exact candidate checkout")
        file_config = load_env_file(env_file)
        runtime = dict(file_config)
        runtime.update(
            {k: v for k, v in os.environ.items() if k.startswith("CHRONICLE_")}
        )
        evidence.data["provider"] = require_live_env(runtime)
        corpus_root = pack_path.parent.resolve()
        loaded = load_source_pack(pack_path, corpus_root)
        evidence.data["source"] = verify_pack_manifest_hashes(
            loaded["pack"], loaded["uploads"], corpus_root
        )
        evidence.data["compose"] = compose_config_check(env_file)
        evidence.data["interactive_review"] = {
            "auto_decisions": "refused",
            "pause_required": True,
        }
        evidence.data["live_command"] = (
            "python3 apps/chronicle/acceptance/second_round_gate.py "
            f"--mode live --env-file {env_file} "
            f"--source-pack {pack_path} --evidence-dir {evidence_dir}"
        )
        evidence.data["t17_handoff"] = {
            "steps": [
                "start an isolated Compose stack on a fresh CHRONICLE_DATA_DIR",
                "upload the T02 sources through Studio and queue jobs",
                "run staged whole-chapter production and verify the reading chain",
                "resolve every blocking review interactively in Studio",
                "run reading-flow-smoke.mjs against the running Rust/Python stack",
                "record the T17 content acceptance; fixture PASS is not proof",
            ],
            "provider_calls_by_t16": 0,
        }
        evidence.data["result"] = "READY"
        write_json(evidence.manifest_path, evidence.data)
        if evidence.partial_path.exists():
            evidence.partial_path.unlink()
        return evidence.data
    except GateError:
        evidence.fail("live preflight failed")
        raise


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("fixture", "live"))
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--source-pack", required=True)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument(
        "--build",
        action="store_true",
        help="fixture only: build the Chronicle image before starting the stack",
    )
    parser.add_argument(
        "--skip-browser",
        action="store_true",
        help="fixture only: do not run the browser suite",
    )
    parser.add_argument(
        "--browser-required",
        action="store_true",
        help="fixture only: fail unless the browser suite runs and passes",
    )
    parser.add_argument(
        "--keep-stack",
        action="store_true",
        help="fixture only: keep the Compose stack for inspection",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="fixture only: permit a dirty checkout for local iteration",
    )
    parser.add_argument("--auto-decide", action="store_true", help="always refused")
    parser.add_argument(
        "--non-interactive", action="store_true", help="always refused live"
    )
    parser.add_argument(
        "--execute", action="store_true", help="always refused: T17 owns live"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    full_argv = [sys.argv[0], *(argv if argv is not None else sys.argv[1:])]

    def resolve(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else (REPO / path).resolve()

    env_file = resolve(args.env_file)
    pack_path = resolve(args.source_pack)
    evidence_dir = resolve(args.evidence_dir)
    if not env_file.is_file():
        raise GateError(f"env file not found: {env_file}")
    if not pack_path.is_file():
        raise GateError(f"source pack not found: {pack_path}")

    if args.mode == "fixture":
        evidence = run_fixture(
            env_file,
            pack_path,
            evidence_dir,
            full_argv,
            allow_dirty=args.allow_dirty,
            build=args.build,
            run_browser=not args.skip_browser,
            browser_required=args.browser_required,
            keep_stack=args.keep_stack,
        )
        print(f"second-round gate: PASS evidence={evidence_dir / 'manifest.json'}")
        return 0
    run_live(
        env_file,
        pack_path,
        evidence_dir,
        full_argv,
        auto_decide=args.auto_decide,
        non_interactive=args.non_interactive,
        execute=args.execute,
    )
    print(f"second-round gate: READY evidence={evidence_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GateError as exc:
        print(f"second-round gate: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
