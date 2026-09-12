#!/usr/bin/env python3
"""Chronicle third-round person-state automated gate (C2-R3-T14).

Unified thin orchestration entry for the third-round acceptance loop::

    python3 apps/chronicle/acceptance/third_round_gate.py \
        --mode fixture \
        --env-file /tmp/chronicle-r3-test.env \
        --source-pack apps/chronicle/corpus/first-round/source-pack.json \
        --evidence-dir /tmp/chronicle-r3-fixture

``fixture`` mode runs the real deployed stack through the shared
``gate_runtime`` lifecycle (isolated Compose project, PostgreSQL 18, Rust
``chronicle-server`` front, Python ``read_api`` sidecar, durable worker) plus
an in-gate deterministic provider served over the real Responses protocol.
The provider emits the 0.3 chapter candidate (translation + C0 records +
reading annotations + ``person_states``) for chapter prompts, and a
deterministic facts/prose draft for the explicit synthesis (present) stage.

The gate then drives the whole third-round loop over the authenticated Studio
HTTP boundary and the public Rust read routes, with no raw product SQL:

1. upload the frozen first-round sources, queue the 0.3 job, let identity
   resolution finish and the job park on the per-chapter
   ``chapter_state_evidence`` packages;
2. resolve those packages explicitly, resume, and let publication commit the
   catalog / chapters / reading index / person-state manifest atomically;
3. explicitly select the published chapters as synthesis sources, create the
   existing comprehensive history job, and pass the facts and prose review
   gates;
4. read the published HistoryPage and the independent person state through
   the public HTTP routes, recording ``version / paragraph_id / phase_id``
   and the exact original anchors;
5. exercise the fail-closed fault/negative matrix and finally run the real
   browser ``person-state-flow-smoke.mjs`` suite against the running front.

``live`` mode performs the strict prechecks for a real-provider run and stops
with a READY handoff; it disables every fixture decision and never calls a
real provider, so the operator must resolve identity/phase reviews by hand.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

GATE_SCHEMA = "chronicle.third-round-gate-evidence"
GATE_VERSION = "0.3"
BROWSER_MANIFEST_SCHEMA = "chronicle.person-state-flow-fixture"
BROWSER_MANIFEST_VERSION = "0.1"
FIXTURE_DISCLAIMER = (
    "fixture mode is deterministic offline orchestration only; it is NOT "
    "live content proof and MUST NOT be cited as real translation, "
    "person-state or synthesis correctness evidence"
)
VIEWPORTS = (
    {"name": "desktop-1440", "width": 1440, "height": 900},
    {"name": "tablet-1024", "width": 1024, "height": 768},
    {"name": "mobile-390", "width": 390, "height": 844},
    {"name": "narrow-320", "width": 320, "height": 568},
)
PERF_BUDGETS = {
    # person-state-reading.md §9: after data is retrieved, the person/place
    # region update is p95 <=100ms with no per-person N+1 and no main-thread
    # task >=200ms at the R2 5,000-unit / 1,000-group scale.
    "person_region_p95_ms": 100,
    "max_long_task_ms": 200,
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
    compose_config_check,
    default_gate_project,
    free_port,
    json_http,
    load_env_file,
    load_source_pack,
    queue_job,
    require_interactive_stdin,
    require_live_config,
    require_status,
    reviews_for_job,
    safe_provider,
    upload_revision,
    verify_pack_manifest_hashes,
    wait_health,
    wait_job,
    write_compose_override,
    write_json,
)
from reading_scale_fixture import (  # noqa: E402
    SCALE_GROUPS_PLACEHOLDER,
    SCALE_UNITS_PLACEHOLDER,
    SEED_SCRIPT,
    parse_scale_result,
)

import fixture_model  # noqa: E402
import narrative_contract  # noqa: E402

# Pure, candidate-shape agnostic helpers reused from the second-round gate.
# They carry no second-round semantics: they build a grounded event span over
# whatever reading units a candidate owns, poll a public route and assert a
# locator fails closed. Reusing them keeps one implementation instead of a
# parallel copy.
from second_round_gate import (  # noqa: E402
    add_resolved_span,
    create_document,
    public_json,
    _event_ids_from_units,
)

R3_CHAPTER_MODEL = "gate-fixture:person-state-chapter"
R3_NARRATIVE_MODEL = "gate-fixture:narrative"


# ---------------------------------------------------------------------------
# Boundary guards
# ---------------------------------------------------------------------------


def check_no_direct_product_writes() -> dict[str, Any]:
    """Prove this orchestrator never writes product rows with raw SQL.

    Product mutation must go through the deployed stack's public HTTP API or
    the product acceptance entries. Raw INSERT/UPDATE/DELETE/CREATE/DROP/ALTER
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
            "third_round_gate.py must not write product tables directly; "
            f"forbidden tokens present: {hits}"
        )
    return {"direct_product_writes": False, "checked_tokens": len(forbidden)}


def require_fixture_env(config: dict[str, str]) -> None:
    """Fixture mode never calls a real live provider."""
    for key in ("CHRONICLE_MODEL_FIXTURE_PACK", "CHRONICLE_CHAPTER_FIXTURE_PACK"):
        if config.get(key, "").strip():
            raise GateError(
                f"fixture mode refuses {key}; the gate's own HTTP fixture "
                "provider is the only fixture source"
            )


def require_live_env(config: dict[str, str]) -> dict[str, Any]:
    """Strict live-provider preflight for the third round.

    The live run must produce the 0.3 joint chapter candidate and the
    two-gate synthesis draft from the same real provider; a missing model is
    refused instead of silently degrading to a fixture or partial chain.
    """
    for key in ("CHRONICLE_MODEL_FIXTURE_PACK", "CHRONICLE_CHAPTER_FIXTURE_PACK"):
        if config.get(key, "").strip():
            raise GateError(
                f"live mode refuses {key}; fixture material must never enter "
                "a live run"
            )
    require_live_config(config)
    for key in ("CHRONICLE_CHAPTER_MODEL", "CHRONICLE_NARRATIVE_MODEL"):
        if not config.get(key, "").strip():
            raise GateError(f"missing required live configuration: {key}")
    parsed = urllib.parse.urlparse(config["CHRONICLE_MODEL_ENDPOINT"])
    if parsed.username is not None or parsed.password is not None:
        raise GateError("CHRONICLE_MODEL_ENDPOINT must not embed credentials")
    provider = safe_provider(config)
    provider["chapter_model"] = config["CHRONICLE_CHAPTER_MODEL"]
    provider["narrative_model"] = config["CHRONICLE_NARRATIVE_MODEL"]
    provider["candidate_version"] = "0.3"
    return provider


# ---------------------------------------------------------------------------
# Deterministic 0.3 fixture provider served over the real provider protocol
# ---------------------------------------------------------------------------


def pick_unique_mentions(text: str, count: int) -> list[str]:
    """Return ``count`` distinct verbatim snippets occurring once in ``text``."""
    found: list[str] = []
    blocked: set[str] = set()
    for length in (4, 6, 8, 10, 12):
        step = max(1, length // 2)
        for start in range(0, max(0, len(text) - length), step):
            if len(found) >= count:
                return found
            snippet = text[start : start + length]
            if not snippet.strip() or "\n" in snippet or "#" in snippet:
                continue
            if snippet in blocked:
                continue
            if text.count(snippet) != 1:
                continue
            blocked.add(snippet)
            found.append(snippet)
    if len(found) < count:
        raise GateError(
            f"no {count} unique verbatim mentions found in chapter text"
        )
    return found


def grounded_spec(request: dict[str, Any], source_title: str) -> dict[str, Any]:
    """Build a 0.3-valid fixture spec over one program-owned chapter request.

    Two grounded person entities are emitted (subject + a second person) so
    the person-state block carries an attestation fact and its continuity in
    addition to the phase and unit bindings; a missing second unique mention
    still yields a valid empty-state chapter rather than a fabricated one.
    """
    text = request["normalized_text"]
    mentions = pick_unique_mentions(text, 2)
    entities = [
        {"mention": mention, "type": "person", "name": mention}
        for mention in mentions
    ]
    first = mentions[0]
    return {
        "chapter_id": request["chapter_id"],
        "revision_id": request["revision_id"],
        "source_title": source_title,
        "translation_text": f"fixture白話譯文（{first}）非真實譯文",
        "entities": entities,
        "event": {"type": "appointment", "title": f"fixture事件（{first}）"},
        "predicate": "affected",
    }


def chapter_candidate(prompt: str) -> str:
    """Answer a 0.3 joint chapter prompt with a deterministic person-state candidate."""
    request = fixture_model._chapter_request_from_t05_prompt(prompt)
    spec = grounded_spec(request, "gate-fixture")
    candidate = fixture_model.build_person_state_chapter_candidate(request, spec)
    add_resolved_span(candidate, request)
    return json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))


def narrative_drafts(
    context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Deterministic facts/prose draft over a real synthesis context.

    This is the exact draft generator the product narrative contract tests
    use; it covers every source with one phase and one conclusion, keeps the
    reviewer-visible attribution, and serialises the required source
    relations. The product validator and both review gates still run on the
    result, so this only removes the real model call, not a correctness gate.
    """
    sources = context["sources"]
    phases: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    paragraphs: list[dict[str, Any]] = []
    for index, source in enumerate(sources):
        phase, fact = f"p{index}", f"f{index}"
        entity = next(iter(source.get("canonical_refs", {}).get("entities", {}).values()), None)
        event = next(iter(source.get("canonical_refs", {}).get("events", {}).values()), None)
        evidence = source["evidence"][0]["id"]
        phases.append(
            {
                "id": phase,
                "label": source["title"],
                "year": None,
                "period": None,
                "basis": [evidence],
                "relation_to_previous": "uncertain",
            }
        )
        facts.append(
            {
                "id": fact,
                "question": "这一来源如何描述人物？",
                "subject_id": entity,
                "event_id": event,
                "dimension": "event_detail",
                "phase_ids": [phase],
                "text": source["evidence"][0]["quote"],
                "value": None,
                "certainty": "clear",
                "reason": "限于这份来源明确记载的范围。",
                "evidence": [
                    {
                        "id": evidence,
                        "relation": "support",
                        "attribution": "本传作者",
                        "note": "原文明载。",
                    }
                ],
            }
        )
        paragraphs.append(
            {
                "id": f"n{index}",
                "phase_id": phase,
                "segments": [
                    {
                        "text": source["translation"][0]["text"],
                        "conclusion_ids": [fact],
                        "event_id": event,
                        "event_relation": "current" if event else None,
                        "event_text": None,
                    }
                ],
                "entities": [{"entity_id": entity, "importance": "primary"}] if entity else [],
            }
        )
    relations = [
        {
            "left": a["source_id"],
            "right": b["source_id"],
            "relation": "unknown",
            "reason": "此测试不对史料独立性作断言。",
        }
        for a, b in itertools.combinations(sources, 2)
    ]
    return (
        {
            "schema": "chronicle.source-corroboration",
            "version": "0.1",
            "title": "第三轮 fixture 综合叙事（非真实内容）",
            "phases": phases,
            "conclusions": facts,
            "source_relations": relations,
        },
        {
            "schema": "chronicle.historical-narrative",
            "version": "0.1",
            "paragraphs": paragraphs,
            "entry_points": [
                {
                    "label": "阅读入口",
                    "kind": "period",
                    "paragraph_id": "n0",
                    "event_id": None,
                    "reason": "概览这一组已核对资料的完整历史发展。",
                }
            ],
        },
    )


def add_reviewed_person_states(
    context: dict[str, Any],
    facts: dict[str, Any],
    prose: dict[str, Any],
) -> None:
    """Fold the reviewed source person states into the fixture facts/prose.

    Every published 0.3 source carries reviewed, version-fixed
    ``reviewed_person_states``. The fixture synthesis turns each into one
    reviewed office conclusion bound to that source's own phase (never by
    year/event-name equivalence) and links it from the matching paragraph, so
    the published history body actually exercises paragraph person state.
    """
    for index, source in enumerate(context["sources"]):
        for state in source.get("reviewed_person_states") or []:
            person_id = state.get("person_id")
            value = state.get("value") or state.get("target")
            if not person_id or not value:
                continue
            conclusion_id = f"s{index}"
            if any(item["id"] == conclusion_id for item in facts["conclusions"]):
                continue
            facts["conclusions"].append(
                {
                    "id": conclusion_id,
                    "question": "该人物在此阶段的身份",
                    "subject_id": person_id,
                    "event_id": None,
                    "dimension": "office",
                    "phase_ids": [f"p{index}"],
                    "text": "据已审核来源阶段资料，该人物在此阶段有此身份。",
                    "value": str(value),
                    "certainty": state.get("certainty", "uncertain"),
                    "reason": "据已审核来源阶段资料。",
                    "evidence": [
                        {
                            "id": source["evidence"][0]["id"],
                            "relation": "support",
                            "attribution": "本传作者",
                            "note": "已审核来源阶段资料。",
                        }
                    ],
                }
            )
            prose["paragraphs"][index]["segments"][0]["conclusion_ids"].append(
                conclusion_id
            )


def _narrative_context(prompt: str) -> dict[str, Any]:
    marker = "\nINPUT="
    at = prompt.find(marker)
    if at < 0:
        raise GateError("narrative prompt is missing the INPUT section")
    rest = prompt[at + len(marker):]
    line = rest.split("\n", 1)[0]
    context = json.loads(line)
    if not isinstance(context, dict) or not context.get("sources"):
        raise GateError("narrative prompt INPUT carries no sources")
    return context


def narrative_candidate(prompt: str) -> str:
    """Answer a facts/prose synthesis prompt with a deterministic draft."""
    kind = prompt.split("\nSTAGE=")[1].split("\n", 1)[0]
    if kind not in ("facts", "prose"):
        raise GateError(f"unknown narrative stage {kind!r}")
    context = _narrative_context(prompt)
    facts, prose = narrative_drafts(context)
    add_reviewed_person_states(context, facts, prose)
    return json.dumps(facts if kind == "facts" else prose, ensure_ascii=False)


class ThirdRoundFixtureProvider:
    """In-gate HTTP provider implementing the Responses-style protocol."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        #: When set, any prompt containing this token receives a malformed
        #: candidate so the gate can inject a deterministic mid-chain failure.
        self.fail_token: str | None = None
        self.calls: list[str] = []

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
                    elif "\nSTAGE=" in prompt and "CHAPTER REQUEST\n" not in prompt:
                        text = narrative_candidate(prompt)
                        provider.calls.append("narrative")
                    else:
                        text = chapter_candidate(prompt)
                        provider.calls.append("chapter")
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


# ---------------------------------------------------------------------------
# Stack environment
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
    # The paired suffix selects the 0.3 candidate generation inside the worker
    # (chapter_stage.candidate_version_for_model) and the synthesis model.
    config["CHRONICLE_CHAPTER_MODEL"] = R3_CHAPTER_MODEL
    config["CHRONICLE_NARRATIVE_MODEL"] = R3_NARRATIVE_MODEL
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


# ---------------------------------------------------------------------------
# Studio HTTP boundary: review resolution and the full source/synthesis chain
# ---------------------------------------------------------------------------


def resolve_resolution_review(base_url: str, auth: str, item: dict[str, Any]) -> dict[str, Any]:
    allowed = list(item.get("allowed_decisions") or [])
    decision = "same" if "same" in allowed else (allowed[0] if allowed else "uncertain")
    status, payload = json_http(
        base_url,
        f"/api/v1/studio/jobs/reviews/{item['review_id']}/decision",
        method="POST",
        body=json.dumps(
            {
                "decision": decision,
                "rationale": "fixture mode fixed resolution decision",
                "confidence": 1.0,
            }
        ).encode("utf-8"),
        content_type="application/json",
        auth=auth,
    )
    require_status(status, 200, payload, "resolution decision")
    return {"review_id": item["review_id"], "scope": "resolution", "decision": decision}


def resolve_person_state_review(base_url: str, auth: str, item: dict[str, Any]) -> dict[str, Any]:
    """Accept every frozen phase candidate with an explicit, stated default.

    The contract refuses an implicit ``supported`` default, so the fixture
    decision states both the default and a plan-level rationale. The live
    path never calls this: its operator reviews candidate by candidate.
    """
    fingerprint = item.get("plan_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise GateError(
            f"person-state review {item.get('review_id')} carries no plan fingerprint"
        )
    status, payload = json_http(
        base_url,
        f"/api/v1/studio/jobs/reviews/{item['review_id']}/decision",
        method="POST",
        body=json.dumps(
            {
                "plan_fingerprint": fingerprint,
                "default_assessment": "supported",
                "overrides": [],
                "rationale": "fixture mode: 整章阶段依据逐项核对原文后确认。",
            }
        ).encode("utf-8"),
        content_type="application/json",
        auth=auth,
    )
    require_status(status, 200, payload, "person-state decision")
    return {
        "review_id": item["review_id"],
        "scope": "person_state",
        "chapter_id": item.get("chapter_id"),
        "candidate_count": item.get("candidate_count"),
    }


def resolve_narrative_review(base_url: str, auth: str, item: dict[str, Any]) -> dict[str, Any]:
    """Approve one facts/prose candidate with explicit conclusion coverage."""
    status, detail = json_http(
        base_url,
        f"/api/v1/studio/jobs/reviews/{item['review_id']}",
        auth=auth,
    )
    require_status(status, 200, detail, "narrative review detail")
    review = detail.get("review") or {}
    narrative = review.get("narrative") or {}
    candidate_sha = narrative.get("candidate_sha") or item.get("candidate_sha")
    if not isinstance(candidate_sha, str) or not candidate_sha:
        raise GateError(f"narrative review {item.get('review_id')} carries no candidate sha")
    body: dict[str, Any] = {
        "candidate_sha": candidate_sha,
        "decision": "approve",
        "rationale": "fixture mode: 已核对逐条结论与正文来源覆盖。",
    }
    kind = narrative.get("kind") or item.get("narrative_kind")
    if kind == "facts":
        candidate = narrative.get("candidate") or {}
        body["reviewed_conclusion_ids"] = [
            fact["id"] for fact in candidate.get("conclusions", [])
        ]
    status, payload = json_http(
        base_url,
        f"/api/v1/studio/jobs/reviews/{item['review_id']}/decision",
        method="POST",
        body=json.dumps(body).encode("utf-8"),
        content_type="application/json",
        auth=auth,
    )
    require_status(status, 200, payload, "narrative decision")
    return {"review_id": item["review_id"], "scope": "narrative", "kind": kind}


def resolve_open_reviews(
    base_url: str, auth: str, job_id: str, evidence: dict[str, Any]
) -> int:
    """Resolve every open review for one job, branching on its review scope."""
    items = reviews_for_job(base_url, auth, job_id, "open", review_scope="all")
    for item in items:
        scope = item.get("scope")
        if scope == "person_state":
            record = resolve_person_state_review(base_url, auth, item)
        elif scope == "narrative":
            record = resolve_narrative_review(base_url, auth, item)
        else:
            record = resolve_resolution_review(base_url, auth, item)
        evidence.setdefault("review_decisions", []).append(record)
    return len(items)


def resume_and_wait(
    base_url: str, auth: str, job_id: str
) -> dict[str, Any]:
    status, payload = json_http(
        base_url,
        f"/api/v1/studio/jobs/{job_id}/resume",
        method="POST",
        body=b"{}",
        content_type="application/json",
        auth=auth,
    )
    require_status(status, 200, payload, "job resume")
    return wait_job(
        base_url,
        auth,
        job_id,
        wanted={"completed", "failed", "cancelled", "needs_review"},
        timeout_seconds=1800,
        idle_timeout_seconds=600,
    )


def drive_job(
    base_url: str,
    auth: str,
    job_id: str,
    evidence: "Evidence",
    *,
    max_review_rounds: int = 6,
) -> dict[str, Any]:
    """Drive one job through its review gates until it is terminal.

    Third-round jobs can park more than once: identity resolution first, then
    the per-chapter person-state package (and, for synthesis, facts then
    prose). Each round resolves exactly the open packages and resumes; a job
    that exhausts the bounded rounds without reaching a terminal state fails
    closed instead of looping forever.
    """
    current = wait_job(
        base_url,
        auth,
        job_id,
        wanted={"completed", "failed", "cancelled", "needs_review"},
        timeout_seconds=1800,
        idle_timeout_seconds=600,
    )
    for _ in range(max_review_rounds):
        status = current.get("status")
        if status == "completed":
            return current
        if status in ("failed", "cancelled"):
            raise GateError(f"job {job_id} ended {status}: {(current.get('error') or '')[:300]}")
        if status != "needs_review":
            raise GateError(f"job {job_id} unexpected state {status!r}")
        evidence.data["review_rounds"] = int(evidence.data.get("review_rounds", 0)) + 1
        resolve_open_reviews(base_url, auth, job_id, evidence.data)
        evidence.checkpoint()
        current = resume_and_wait(base_url, auth, job_id)
    raise GateError(f"job {job_id} still needs review after {max_review_rounds} rounds")


def publish_upload(
    base_url: str, auth: str, upload: dict[str, Any], evidence: "Evidence"
) -> dict[str, Any]:
    document = create_document(
        base_url, auth, upload["work"] or Path(upload["upload"]).name
    )
    revision = upload_revision(
        base_url, auth, document["document_id"], Path(upload["path"]), "c2r3-gate"
    )
    job = queue_job(base_url, auth, revision["revision_id"])
    current = drive_job(base_url, auth, job["job_id"], evidence)
    if current.get("status") != "completed":
        raise GateError(
            f"source job {job['job_id']} did not publish: {current.get('status')}"
        )
    return {
        "document_id": document["document_id"],
        "revision_id": revision["revision_id"],
        "job_id": job["job_id"],
        "upload": upload["upload"],
        "source_title": upload["work"] or Path(upload["upload"]).name,
    }


# -- synthesis (explicit comprehensive history job) --------------------------


def list_history_sources(base_url: str, auth: str) -> dict[str, Any]:
    status, payload = json_http(
        base_url, "/api/v1/studio/jobs/history/sources?limit=100", auth=auth
    )
    require_status(status, 200, payload, "history source choices")
    if not payload.get("items"):
        raise GateError("no published chapters are selectable for synthesis")
    return payload


def queue_synthesis(
    base_url: str, auth: str, catalog_sha: str, publication_ids: list[str]
) -> dict[str, Any]:
    status, payload = json_http(
        base_url,
        "/api/v1/studio/jobs/history",
        method="POST",
        body=json.dumps(
            {"catalog_sha": catalog_sha, "publication_ids": publication_ids}
        ).encode("utf-8"),
        content_type="application/json",
        auth=auth,
    )
    require_status(status, 201, payload, "queue synthesis job")
    return payload["job"]


def select_synthesis_sources(
    base_url: str, auth: str
) -> tuple[str, list[str], str, dict[str, list[dict[str, Any]]]]:
    """Pick the smallest published document as the comprehensive scope.

    Whole-context synthesis fails closed when the prompt exceeds the fixed
    budget, so the fixture explicitly selects the smallest document instead
    of truncating. All groups stay recorded as available.
    """
    choices = list_history_sources(base_url, auth)
    catalog_sha = choices["catalog_sha"]
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in choices["items"]:
        groups.setdefault(str(item.get("document_title") or item["title"]), []).append(item)
    if not groups:
        raise GateError("no selectable synthesis source")
    title, selected = min(groups.items(), key=lambda pair: (len(pair[1]), pair[0]))
    return catalog_sha, [item["publication_id"] for item in selected], title, groups


def run_synthesis(
    base_url: str, auth: str, evidence: "Evidence"
) -> dict[str, Any]:
    """Explicitly select published sources, run the comprehensive job, publish."""
    catalog_sha, publication_ids, title, groups = select_synthesis_sources(
        base_url, auth
    )
    evidence.data["synthesis_scope"] = {
        "document_title": title,
        "chapter_count": len(publication_ids),
        "available_documents": sorted(groups),
        "catalog_sha": catalog_sha,
    }
    job = queue_synthesis(base_url, auth, catalog_sha, publication_ids)
    current = drive_job(base_url, auth, job["job_id"], evidence)
    if current.get("status") != "completed":
        raise GateError(
            f"synthesis job {job['job_id']} did not publish: {current.get('status')}"
        )
    directory = public_json(base_url, "/api/v1/public/history")
    publication = directory.get("publication")
    if not isinstance(publication, dict) or not publication.get("version"):
        raise GateError("published synthesis exposes no history version")
    return {
        "job_id": job["job_id"],
        "catalog_sha": catalog_sha,
        "publication_ids": publication_ids,
        "document_title": title,
        "version": publication["version"],
        "paragraph_count": publication["paragraph_count"],
    }


def park_source_at_person_state(
    base_url: str, auth: str, upload: dict[str, Any], evidence_dir: Path
) -> str:
    """Leave one real source job parked on its open person-state packages.

    The browser's mixed-queue suite needs a genuinely open
    ``chapter_state_evidence`` package: the gate resolves identity reviews but
    deliberately stops before the person-state decision, so nothing is faked.
    """
    source = evidence_dir / "park-source.md"
    source.write_text(upload["text"] + "\n\n審核草稿段落。\n", encoding="utf-8")
    document = create_document(base_url, auth, "park-source")
    revision = upload_revision(
        base_url, auth, document["document_id"], source, "c2r3-park"
    )
    job = queue_job(base_url, auth, revision["revision_id"])
    for _ in range(6):
        current = wait_job(
            base_url,
            auth,
            job["job_id"],
            wanted={"completed", "failed", "cancelled", "needs_review"},
            timeout_seconds=1200,
            idle_timeout_seconds=600,
        )
        status = current.get("status")
        if status in ("failed", "cancelled"):
            raise GateError(f"parked source job ended {status}")
        if status == "completed":
            raise GateError("parked source job published instead of parking")
        items = reviews_for_job(base_url, auth, job["job_id"], "open", review_scope="all")
        scopes = {item.get("scope") for item in items}
        if "person_state" in scopes:
            return job["job_id"]
        for item in items:
            if item.get("scope") == "resolution":
                resolve_resolution_review(base_url, auth, item)
        current = resume_and_wait(base_url, auth, job["job_id"])
    raise GateError("source job never parked on a person-state package")



# -- published history + person page reads -----------------------------------


def collect_history(base_url: str, version: str) -> dict[str, Any]:
    """Read the published HistoryPage and the exact person-state anchors.

    Records ``version / paragraph_id / phase_id`` plus the original source
    anchor for the first paragraph that carries an entity state, and verifies
    a person-page read of the same version reaches the entity's state panel.
    Only public HTTP reads are used; a source-only ReadingPage is not proof.
    """
    directory = public_json(base_url, f"/api/v1/public/history?version={version}")
    publication = directory["publication"]
    page = public_json(
        base_url,
        f"/api/v1/public/history/paragraphs?version={version}&limit=50",
    )
    paragraphs = page["paragraphs"]
    if not paragraphs:
        raise GateError("published synthesis exposes no paragraphs")
    anchor_paragraph = None
    for paragraph in paragraphs:
        if paragraph.get("entities"):
            for entity in paragraph["entities"]:
                if entity.get("states"):
                    anchor_paragraph = (paragraph, entity)
                    break
        if anchor_paragraph:
            break
    if anchor_paragraph is None:
        raise GateError(
            "published history paragraphs carry no entity state; the person-state "
            "loop did not reach the composite body"
        )
    paragraph, entity = anchor_paragraph
    state = entity["states"][0]
    conclusion = public_json(
        base_url,
        f"/api/v1/public/history/conclusions/{state['id']}?version={version}",
    )
    evidence = conclusion["conclusion"]["evidence"]
    if not evidence:
        raise GateError("published person state carries no original evidence anchor")
    record = {
        "version": version,
        "catalog_sha": directory["publication"]["catalog_sha"],
        "paragraph_id": paragraph["id"],
        "phase_id": paragraph["phase_id"],
        "entity_id": entity["id"],
        "state_id": state["id"],
        "value": state.get("value"),
        "certainty": state.get("certainty"),
        "conclusion_id": conclusion["conclusion"]["id"],
        "anchor_id": evidence[0].get("anchor_id"),
        "anchor_quote": evidence[0].get("quote"),
        "paragraph_count": publication["paragraph_count"],
        "entry_points": [entry["paragraph_id"] for entry in publication.get("entry_points", [])],
    }
    # Independent person page: the same version anchored at that paragraph must
    # expose the entity phase state; a missing person detail must fail closed.
    person_page = public_json(
        base_url,
        f"/api/v1/public/history/paragraphs?version={version}&at={paragraph['id']}",
    )
    target = next(
        (p for p in person_page["paragraphs"] if p["id"] == paragraph["id"]), None
    )
    if target is None or target["phase_id"] != paragraph["phase_id"]:
        raise GateError("person-page paragraph read did not return the anchored phase")
    record["person_page_phase_id"] = target["phase_id"]
    return record


def source_state_inconsistencies(
    probes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return probes where a published unit exposed an out-of-context person.

    The read API answers ``409 inconsistent`` for such a unit. The gate treats
    any occurrence as a hard failure: recording it as a known issue is not a
    substitute for the fail-closed contract.
    """
    return [probe for probe in probes if probe.get("status") == 409]


def require_source_state_consistency(probes: list[dict[str, Any]]) -> None:
    """Fail closed (never PASS) when any source unit exposed an out-of-context person."""
    rejected = source_state_inconsistencies(probes)
    if rejected:
        raise GateError(
            "multi_chapter_source_state_consistency != PASS: "
            f"{len(rejected)} published reading unit(s) expose person-state "
            "outside their context; refusing to report an overall PASS"
        )


def collect_source_person(
    base_url: str, works: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read a consistent source-reading person state through the public routes.

    The read API fails closed (409 ``inconsistent``) when a published unit
    exposes a person outside that unit's own context. The gate probes every
    work/unit and returns the first consistent read, recording each rejection
    so the caller fails closed with exact evidence.
    """
    probes: list[dict[str, Any]] = []
    positive: dict[str, Any] | None = None
    for work in works:
        stream_id = work["stream_id"]
        catalog = work["catalog_sha"]
        units = public_json(
            base_url,
            f"/api/v1/public/reading-streams/{stream_id}/units"
            f"?catalog={catalog}&limit=10",
        )["page"]["units"]
        for unit in units:
            unit_id = unit["unit_id"]
            status, payload = json_http(
                base_url,
                f"/api/v1/public/reading-streams/{stream_id}/units/{unit_id}/people"
                f"?catalog={catalog}&limit=6",
            )
            entry: dict[str, Any] = {
                "stream_id": stream_id,
                "catalog_sha": catalog,
                "unit_id": unit_id,
                "stream_unit_count": work.get("unit_count"),
                "status": status,
            }
            if status == 200 and payload.get("people"):
                person_id = payload["people"][0]["person_id"]
                state_status, states = json_http(
                    base_url,
                    f"/api/v1/public/reading-streams/{stream_id}/units/{unit_id}"
                    f"/people/{person_id}/states?catalog={catalog}"
                    "&section=identities&limit=20",
                )
                entry["person_id"] = person_id
                entry["state_status"] = state_status
                entry["state_count"] = (
                    len(states.get("items") or []) if state_status == 200 else 0
                )
                probes.append(entry)
                if positive is None:
                    positive = {
                        "stream_id": stream_id,
                        "catalog_sha": catalog,
                        "unit_id": unit_id,
                        "person_id": person_id,
                        "section": "identities",
                        "state_count": entry["state_count"],
                    }
                break
            entry["error_code"] = (payload.get("error") or {}).get("code")
            probes.append(entry)
        if positive is not None:
            break
    if positive is None:
        raise GateError(f"no consistent source person-state read; probes={probes}")
    return positive, probes


# ---------------------------------------------------------------------------
# Fault and negative matrix on the real stack
# ---------------------------------------------------------------------------


def fault_checks(
    stack: ComposeStack,
    base_url: str,
    auth: str,
    upload: dict[str, Any],
    history: dict[str, Any],
    *,
    provider: ThirdRoundFixtureProvider,
    evidence_dir: Path,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    faults: dict[str, Any] = {}
    version = history["version"]

    # F1: a deterministic mid-chain chapter failure leaves no public half-product.
    before = public_json(base_url, "/api/v1/public/history")
    before_version = (before.get("publication") or {}).get("version")
    token = "GATEFAULTTOKEN"
    fault_source = evidence_dir / "fault-source.md"
    fault_source.write_text(upload["text"] + f"\n\n{token}\n", encoding="utf-8")
    provider.fail_token = token
    try:
        document = create_document(base_url, auth, "fault-source")
        revision = upload_revision(
            base_url, auth, document["document_id"], fault_source, "c2r3-fault"
        )
        job = queue_job(base_url, auth, revision["revision_id"])
        failed = wait_job(
            base_url, auth, job["job_id"], wanted={"failed"}, timeout_seconds=600
        )
    finally:
        provider.fail_token = None
    if failed.get("status") != "failed":
        raise GateError("injected chapter failure did not fail the job")
    after = public_json(base_url, "/api/v1/public/history")
    after_version = (after.get("publication") or {}).get("version")
    if after_version != before_version:
        raise GateError("failed source chain leaked a published history version")
    faults["chain_failure_no_partial"] = {
        "passed": True,
        "job_status": "failed",
        "error": (failed.get("error") or "")[:200],
    }

    # F2: restart/redeploy keeps the published version and person state readable.
    stack.restart("chronicle-web", "chronicle-read")
    wait_health(base_url, timeout_seconds=180)
    restart = public_json(base_url, "/api/v1/public/history")
    if (restart.get("publication") or {}).get("version") != version:
        raise GateError("published history version changed across restart")
    reparsed = collect_history(base_url, version)
    if reparsed["paragraph_id"] != history["paragraph_id"]:
        raise GateError("person-state anchor changed across restart")
    faults["restart_preserves_published"] = {"passed": True, "version": version}

    # F3: unknown fixed version and unknown paragraph fail closed via public HTTP.
    bad_version, _ = json_http(
        base_url, f"/api/v1/public/history/paragraphs?version={'0' * 64}"
    )
    if bad_version not in (400, 404):
        raise GateError(f"unknown history version must fail closed, got {bad_version}")
    bad_paragraph, _ = json_http(
        base_url,
        f"/api/v1/public/history/paragraphs?version={version}&at=hp_{'0' * 24}",
    )
    if bad_paragraph not in (400, 404):
        raise GateError(
            f"unknown history paragraph must fail closed, got {bad_paragraph}"
        )
    faults["unknown_version_and_paragraph_refused"] = {
        "passed": True,
        "version_status": bad_version,
        "paragraph_status": bad_paragraph,
    }

    # F4: the synthesis version is fixed; a source-only stream cannot stand in.
    source_only, _ = json_http(
        base_url,
        f"/api/v1/public/history/conclusions/{history['state_id']}"
        f"?version={'0' * 64}",
    )
    if source_only not in (400, 404):
        raise GateError(
            "a source-only conclusion must not resolve under a fixed history version"
        )
    faults["source_only_not_history"] = {
        "passed": True,
        "status": source_only,
    }

    evidence["faults"] = faults
    return faults


# ---------------------------------------------------------------------------
# Synthetic scale fixture + browser manifest
# ---------------------------------------------------------------------------


def seed_scale_stream(
    stack: ComposeStack, *, units: int, groups: int
) -> dict[str, Any]:
    script = SEED_SCRIPT.replace(SCALE_UNITS_PLACEHOLDER, str(units)).replace(
        SCALE_GROUPS_PLACEHOLDER, str(groups)
    )
    result = stack.compose_run_script("chronicle-worker", script)
    return parse_scale_result(result.stdout)


def build_browser_manifest(
    *,
    base_url: str,
    history: dict[str, Any],
    source_person: dict[str, Any],
    scale: dict[str, Any],
    review_jobs: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": BROWSER_MANIFEST_SCHEMA,
        "version": BROWSER_MANIFEST_VERSION,
        "generated_by": "C2-R3-T14",
        "base_url": base_url,
        "history": {
            "version": history["version"],
            "catalog_sha": history["catalog_sha"],
            "paragraph_id": history["paragraph_id"],
            "phase_id": history["phase_id"],
            "entity_id": history["entity_id"],
            "state_id": history["state_id"],
            "certainty": history["certainty"],
            "paragraph_count": history["paragraph_count"],
        },
        "source_person": source_person,
        "review": {
            "review_scope": "all",
            "person_state_job_id": review_jobs["person_state_job_id"],
        },
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
    """Fail closed when the manifest the person-state driver depends on is incomplete."""
    if not isinstance(manifest, dict):
        raise GateError("person-state browser manifest must be a JSON object")
    if manifest.get("schema") != BROWSER_MANIFEST_SCHEMA:
        raise GateError(
            f"browser manifest schema must be {BROWSER_MANIFEST_SCHEMA!r}"
        )
    history = manifest.get("history")
    if not isinstance(history, dict):
        raise GateError("browser manifest carries no published history")
    for field in (
        "version",
        "catalog_sha",
        "paragraph_id",
        "phase_id",
        "entity_id",
        "state_id",
    ):
        if not history.get(field):
            raise GateError(f"browser manifest history missing {field!r}")
    if len(str(history["catalog_sha"])) != 64:
        raise GateError("browser manifest catalog_sha must be 64 hex chars")
    source_person = manifest.get("source_person")
    if not isinstance(source_person, dict) or not source_person.get("person_id"):
        raise GateError("browser manifest carries no source person state")
    for field in ("stream_id", "catalog_sha", "unit_id", "person_id"):
        if not source_person.get(field):
            raise GateError(f"browser manifest source_person missing {field!r}")
    review = manifest.get("review")
    if not isinstance(review, dict):
        raise GateError("browser manifest carries no parked review jobs")
    if not review.get("person_state_job_id"):
        raise GateError("browser manifest review missing 'person_state_job_id'")
    scale = manifest.get("scale")
    if not isinstance(scale, dict) or not scale.get("stream_id"):
        raise GateError("browser manifest carries no synthetic scale stream")
    if int(scale.get("unit_count", 0)) < PERF_BUDGETS["target_units"]:
        raise GateError(
            f"synthetic scale stream below the 5,000-unit target: {scale.get('unit_count')}"
        )
    if int(scale.get("group_count", 0)) < PERF_BUDGETS["target_groups"]:
        raise GateError(
            f"synthetic scale stream below the 1,000-group target: {scale.get('group_count')}"
        )
    if not isinstance(manifest.get("viewports"), list) or not manifest["viewports"]:
        raise GateError("browser manifest carries no viewports")
    budgets = manifest.get("budgets")
    if not isinstance(budgets, dict):
        raise GateError("browser manifest carries no budgets")
    for key in ("person_region_p95_ms", "max_long_task_ms", "mounted_max_units"):
        if not isinstance(budgets.get(key), int):
            raise GateError(f"browser manifest budget {key!r} is missing")
    return manifest


def run_browser_driver(
    manifest_path: Path,
    *,
    base_url: str,
    suite: str,
    output_dir: Path,
    username: str,
    password: str,
) -> dict[str, Any]:
    script = (
        REPO / "apps" / "chronicle" / "webapp" / "scripts" / "person-state-flow-smoke.mjs"
    )
    if not script.is_file():
        raise GateError(f"person-state browser driver is missing: {script}")
    if not shutil.which("node"):
        raise GateError("node is required to run the person-state browser driver")
    output_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["CHRONICLE_SMOKE_USERNAME"] = username
    env["CHRONICLE_SMOKE_PASSWORD"] = password
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
        env=env,
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
            f"person-state-flow-smoke failed ({result.returncode}); see {output_dir}: "
            f"{(result.stdout + result.stderr)[-1500:]}"
        )
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise GateError(f"person-state-flow-smoke did not report ok=true: {payload}")
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
    provider = ThirdRoundFixtureProvider(free_port())
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
                key for key in file_config if key.startswith("CHRONICLE_")
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
        override = write_compose_override(
            evidence_dir / "compose.gate.yaml", service="chronicle-worker"
        )
        data_dir = evidence_dir / "stack-data"
        data_dir.mkdir(parents=True, exist_ok=True)
        base_url = "http://127.0.0.1:18080"
        stack = ComposeStack(
            repo=REPO,
            env_file=stack_env,
            project=default_gate_project("r3"),
            data_dir=data_dir,
            base_url=base_url,
            worker_lease_seconds=30,
            extra_files=[str(override)],
        )
        stack.up(build=build)
        wait_health(base_url, timeout_seconds=300)
        config = load_env_file(stack_env)
        auth = basic_auth(
            config["CHRONICLE_ADMIN_USER"], config["CHRONICLE_ADMIN_PASSWORD"]
        )
        evidence.data["stack"] = {
            "project": stack.project,
            "base_url": base_url,
            "fixture_endpoint": endpoint,
            "image_built": build,
        }
        evidence.checkpoint()

        # 1/2. Source 0.3 chain: upload -> generate -> identity/phase review ->
        # atomic publish of catalog + chapters + reading index + manifest.
        works: list[dict[str, Any]] = []
        for upload in loaded["uploads"]:
            published = publish_upload(base_url, auth, upload, evidence)
            latest = public_json(base_url, "/api/v1/public/reading-streams")
            source_catalog = latest["snapshot"]["catalog_sha"]
            stream = public_json(
                base_url,
                f"/api/v1/public/reading-streams?catalog={source_catalog}",
            )
            match = next(
                (
                    item
                    for item in stream["page"]["streams"]
                    if item.get("revision_id") == published["revision_id"]
                ),
                None,
            )
            if match is None:
                raise GateError("published 0.3 revision is missing from the public directory")
            published["stream_id"] = match["stream_id"]
            published["catalog_sha"] = source_catalog
            published["unit_count"] = int(match["unit_count"])
            published["group_count"] = int(match["group_count"])
            units = public_json(
                base_url,
                f"/api/v1/public/reading-streams/{match['stream_id']}/units"
                f"?catalog={source_catalog}&limit=50",
            )
            published["first_unit_id"] = units["page"]["units"][0]["unit_id"]
            published["event_ids"] = _event_ids_from_units(units["page"]["units"])
            works.append(published)
            evidence.data["works"] = works
            evidence.checkpoint()

        # 3. Explicit comprehensive history job with both review gates.
        synthesis = run_synthesis(base_url, auth, evidence)
        evidence.data["synthesis"] = synthesis
        evidence.checkpoint()

        # 4. Published HistoryPage + independent person-state reads.
        history = collect_history(base_url, synthesis["version"])
        evidence.data["history"] = history
        source_person, source_probes = collect_source_person(base_url, works)
        evidence.data["source_person"] = source_person
        evidence.data["source_person_reads"] = source_probes
        rejected = source_state_inconsistencies(source_probes)
        if rejected:
            evidence.data["known_integration_issues"] = [
                {
                    "issue": (
                        "a published multi-chapter source stream exposes person-state "
                        "items whose person is not in that reading unit's context"
                    ),
                    "observed": rejected,
                    "suspect_root_cause": (
                        "the per-unit person-state compile did not scope the "
                        "revision-wide evidence to the unit's chapter"
                    ),
                    "owning_module": "C2-R3-T04/T08",
                }
            ]
            evidence.checkpoint()
            require_source_state_consistency(source_probes)
        evidence.checkpoint()

        # F. Failure and negative matrix on the real stack.
        evidence.data["faults"] = fault_checks(
            stack,
            base_url,
            auth,
            loaded["uploads"][0],
            history,
            provider=provider,
            evidence_dir=evidence_dir,
            evidence=evidence.data,
        )
        evidence.checkpoint()

        # 5. Synthetic scale stream + browser manifest. When a browser run is
        # requested, park one real source job on person-state and one real
        # synthesis job on facts so the mixed queue has genuinely open forms.
        scale = seed_scale_stream(stack, units=5000, groups=1000)
        evidence.data["scale"] = scale

        if run_browser:
            review_jobs = {
                "person_state_job_id": park_source_at_person_state(
                    base_url, auth, loaded["uploads"][0], evidence_dir
                ),
            }
            evidence.data["parked_review_jobs"] = review_jobs
            evidence.checkpoint()
            manifest = validate_browser_manifest(
                build_browser_manifest(
                    base_url=base_url,
                    history=history,
                    source_person=source_person,
                    scale=scale,
                    review_jobs=review_jobs,
                )
            )
            manifest_path = evidence_dir / "person-state-fixture-manifest.json"
            write_json(manifest_path, manifest)
            evidence.data["browser_manifest"] = {
                "path": str(manifest_path),
                "schema": manifest["schema"],
                "version": manifest["history"]["version"],
            }
            evidence.data["browser"] = run_browser_driver(
                manifest_path,
                base_url=base_url,
                suite="all",
                output_dir=evidence_dir / "browser",
                username=config["CHRONICLE_ADMIN_USER"],
                password=config["CHRONICLE_ADMIN_PASSWORD"],
            )
        elif browser_required:
            raise GateError("a browser run was required but --skip-browser was set")
        else:
            evidence.data["browser"] = {
                "ok": False,
                "reason": "browser suite skipped by --skip-browser",
            }

        measured = bool(evidence.data["browser"].get("ok"))
        faults_ok = all(
            item.get("passed") for item in evidence.data["faults"].values()
        )
        evidence.data["criteria"] = {
            "source_person_state_publish_chain": "PASS",
            "composite_history_two_review_chain": "PASS",
            "published_history_and_person_page": "PASS",
            "negative_faults": "PASS" if faults_ok else "FAIL",
            "browser_interaction": "PASS" if measured else "NOT_RUN",
            "performance_budget": "PASS" if measured else "NOT_MEASURED",
            "multi_chapter_source_state_consistency": (
                "PASS"
                if not source_state_inconsistencies(
                    evidence.data.get("source_person_reads") or []
                )
                else "FAIL"
            ),
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
# Live mode (strict preflight + READY handoff)
# ---------------------------------------------------------------------------


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
            "live mode refuses --auto-decide; identity and phase decisions require review"
        )
    if non_interactive:
        raise GateError(
            "live mode refuses --non-interactive; reviews pause for an operator"
        )
    if execute:
        raise GateError(
            "this entry issues a READY handoff; the operator live run is T15"
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
            {key: value for key, value in os.environ.items() if key.startswith("CHRONICLE_")}
        )
        evidence.data["provider"] = require_live_env(runtime)
        corpus_root = pack_path.parent.resolve()
        loaded = load_source_pack(pack_path, corpus_root)
        evidence.data["source"] = verify_pack_manifest_hashes(
            loaded["pack"], loaded["uploads"], corpus_root
        )
        evidence.data["compose"] = compose_config_check(REPO, env_file)
        evidence.data["interactive_review"] = {
            "auto_decisions": "refused",
            "fixture_decisions_disabled": True,
            "pause_required": True,
        }
        evidence.data["live_command"] = (
            "python3 apps/chronicle/acceptance/third_round_gate.py "
            f"--mode live --env-file {env_file} "
            f"--source-pack {pack_path} --evidence-dir {evidence_dir}"
        )
        evidence.data["t15_handoff"] = {
            "steps": [
                "start an isolated Compose stack on a fresh CHRONICLE_DATA_DIR",
                "upload the frozen whole chapters through Studio and queue 0.3 jobs",
                "resolve every identity and chapter_state_evidence review by hand",
                "explicitly select published sources and run the comprehensive job",
                "resolve the facts review and the prose review by hand",
                "read the published HistoryPage and independent person pages; record "
                "version/paragraph_id/phase_id and original anchors",
                "run person-state-flow-smoke.mjs against the running stack",
                "record the T15 content acceptance; fixture PASS is not proof",
            ],
            "provider_calls_by_t14": 0,
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
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--skip-browser", action="store_true")
    parser.add_argument("--browser-required", action="store_true")
    parser.add_argument("--keep-stack", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--auto-decide", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    env_file = Path(args.env_file)
    pack_path = Path(args.source_pack)
    evidence_dir = Path(args.evidence_dir)
    if not env_file.is_absolute():
        env_file = (REPO / env_file).resolve()
    if not pack_path.is_absolute():
        pack_path = (REPO / pack_path).resolve()
    if not evidence_dir.is_absolute():
        evidence_dir = (REPO / evidence_dir).resolve()
    raw = list(sys.argv[1:] if argv is None else argv)
    if args.mode == "fixture":
        manifest = run_fixture(
            env_file,
            pack_path,
            evidence_dir,
            raw,
            allow_dirty=args.allow_dirty,
            build=args.build,
            run_browser=not args.skip_browser,
            browser_required=args.browser_required,
            keep_stack=args.keep_stack,
        )
        print(f"third-round gate: PASS: {evidence_dir / 'manifest.json'}")
        return 0
    manifest = run_live(
        env_file,
        pack_path,
        evidence_dir,
        raw,
        auto_decide=args.auto_decide,
        non_interactive=args.non_interactive,
        execute=args.execute,
    )
    print(f"third-round gate: READY: {evidence_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GateError as exc:
        print(f"third-round gate: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
