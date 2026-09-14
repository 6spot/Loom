#!/usr/bin/env python3
"""Chronicle staged 0.4 production acceptance gate (C3-T01).

This is the single current acceptance entry for source production. Fixture
mode drives the real Rust/Python/PostgreSQL stack through the production
worker and the shared ``gate_runtime`` lifecycle, using only the staged
pipeline fixture's HTTP Responses provider. Live mode performs a strict,
credential-free handoff and never falls back to fixture decisions.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

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
    # task >=200ms at the synthetic 5,000-unit / 1,000-group scale.
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

import staged_chapter_contract  # noqa: E402
import staged_pipeline_fixture as staged_fixture  # noqa: E402
import reading_contract  # noqa: E402

STAGED_CHAPTER_MODEL = "chronicle-staged-fixture-0.4"
STAGED_NARRATIVE_MODEL = "chronicle-staged-fixture-narrative"
GATE_SCHEMA = "chronicle.staged-gate-evidence"
GATE_VERSION = "0.4"
BROWSER_MANIFEST_SCHEMA = "chronicle.person-state-flow-fixture"
READING_BROWSER_MANIFEST_SCHEMA = "chronicle.reading-flow-fixture"
READING_BROWSER_MANIFEST_VERSION = "0.1"


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
            "staged_gate.py must not write product tables directly; "
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
    """Strict live-provider preflight for the current staged 0.4 chain."""
    for key in ("CHRONICLE_MODEL_FIXTURE_PACK", "CHRONICLE_CHAPTER_FIXTURE_PACK"):
        if config.get(key, "").strip():
            raise GateError(
                f"live mode refuses {key}; fixture material must never enter "
                "a live run"
            )
    required = (
        "CHRONICLE_POSTGRES_PASSWORD",
        "CHRONICLE_ADMIN_USER",
        "CHRONICLE_ADMIN_PASSWORD",
        "CHRONICLE_MODEL_ENDPOINT",
        "CHRONICLE_CHAPTER_MODEL",
        "CHRONICLE_NARRATIVE_MODEL",
    )
    missing = [key for key in required if not config.get(key, "").strip()]
    if missing:
        raise GateError(
            "missing required live-gate configuration: " + ", ".join(missing)
        )
    forbidden_models = {
        STAGED_CHAPTER_MODEL,
        STAGED_NARRATIVE_MODEL,
    }
    model_values = [
        config.get("CHRONICLE_CHAPTER_MODEL", ""),
        config.get("CHRONICLE_NARRATIVE_MODEL", ""),
        config.get("CHRONICLE_CHAPTER_REVIEW_MODELS", ""),
    ]
    model_names = [
        name.strip()
        for value in model_values
        for name in value.split(",")
        if name.strip()
    ]
    if any(name.startswith("fixture:") for name in model_names):
        raise GateError("live mode refuses frozen fixture model entries")
    if any(name in forbidden_models for name in model_names):
        raise GateError("live mode refuses the staged acceptance fixture model")
    parsed = urllib.parse.urlparse(config["CHRONICLE_MODEL_ENDPOINT"])
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise GateError("CHRONICLE_MODEL_ENDPOINT must be an absolute http(s) URL")
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise GateError("CHRONICLE_MODEL_ENDPOINT must not embed credentials or query secrets")
    provider = safe_provider(config)
    provider["chapter_model"] = config["CHRONICLE_CHAPTER_MODEL"]
    provider["narrative_model"] = config["CHRONICLE_NARRATIVE_MODEL"]
    provider["candidate_version"] = staged_chapter_contract.CANDIDATE_VERSION
    return provider


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
    # The fixture has a normal model name, so chapter_stage selects the
    # production ChapterModels/0.4 path instead of the historical fixture
    # model families.
    config["CHRONICLE_CHAPTER_MODEL"] = STAGED_CHAPTER_MODEL
    config["CHRONICLE_CHAPTER_REVIEW_MODELS"] = STAGED_CHAPTER_MODEL
    config["CHRONICLE_CHAPTER_PIPELINE_CONFIG"] = ""
    config["CHRONICLE_NARRATIVE_MODEL"] = STAGED_NARRATIVE_MODEL
    for key in ("CHRONICLE_MODEL_FIXTURE_PACK", "CHRONICLE_CHAPTER_FIXTURE_PACK"):
        config.pop(key, None)
    config.pop("CHRONICLE_MODEL_API_KEY", None)
    out.write_text(
        "".join(f"{key}={value}\n" for key, value in sorted(config.items())),
        encoding="utf-8",
    )
    return out


# ---------------------------------------------------------------------------
# Product HTTP boundary helpers
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


def _event_ids_from_units(units: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for unit in units:
        for segment in unit.get("segments", []):
            if segment.get("kind") != "event":
                continue
            event_id = (segment.get("span") or {}).get("target_event_id")
            if event_id and event_id not in seen:
                seen.add(event_id)
                found.append(event_id)
    return found


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

    Staged jobs can park more than once: identity resolution first, then the
    per-chapter person-state package (and, for synthesis, facts then prose).
    Each review round resolves exactly the open packages and resumes; a job
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
        base_url, auth, document["document_id"], Path(upload["path"]), "c3-t01-staged-gate"
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


def publish_revision(
    base_url: str,
    auth: str,
    document_id: str,
    source_path: Path,
    label: str,
    evidence: "Evidence",
) -> dict[str, Any]:
    """Publish a second revision through the same Studio/worker boundary."""
    revision = upload_revision(base_url, auth, document_id, source_path, label)
    queued = queue_job(base_url, auth, revision["revision_id"])
    current = drive_job(base_url, auth, queued["job_id"], evidence)
    if current.get("status") != "completed":
        raise GateError(
            f"revision job {queued['job_id']} did not publish: {current.get('status')}"
        )
    return {
        "document_id": document_id,
        "revision_id": revision["revision_id"],
        "job_id": queued["job_id"],
        "source_title": label,
    }


def collect_published_work(
    base_url: str, published: dict[str, Any]
) -> dict[str, Any]:
    """Collect the public stream and first/last unit evidence for one revision."""
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
        raise GateError(
            f"published staged 0.4 revision {published['revision_id']} "
            "is missing from the public directory"
        )
    units = public_json(
        base_url,
        f"/api/v1/public/reading-streams/{match['stream_id']}/units"
        f"?catalog={source_catalog}&limit=50",
    )["page"]["units"]
    if not units:
        raise GateError(f"published stream {match['stream_id']} exposes no units")
    published.update(
        {
            "stream_id": match["stream_id"],
            "catalog_sha": source_catalog,
            "unit_count": int(match["unit_count"]),
            "group_count": int(match["group_count"]),
            "first_unit_id": units[0]["unit_id"],
            "last_unit_id": units[-1]["unit_id"],
            "event_ids": _event_ids_from_units(units),
        }
    )
    return published


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
    """Select two complete published chapters for distinct fixture phases.

    A one-chapter scope produces only one fixture paragraph and cannot prove
    reading-driven state changes. Keep the scope bounded to two chapters;
    whole-context budget checks still reject oversized input without truncation.
    All document groups remain recorded as available.
    """
    choices = list_history_sources(base_url, auth)
    catalog_sha = choices["catalog_sha"]
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in choices["items"]:
        groups.setdefault(str(item.get("document_title") or item["title"]), []).append(item)
    selected = choices["items"][:2]
    if len(selected) != 2:
        raise GateError("person-state performance requires two complete published chapters")
    title = " / ".join(dict.fromkeys(str(item.get("document_title") or item["title"]) for item in selected))
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
        base_url, auth, document["document_id"], source, "c3-t01-park"
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
    provider: staged_fixture.StagedFixtureProvider,
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
            base_url, auth, document["document_id"], fault_source, "c3-t01-fault"
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


def build_scenario_coverage(
    loaded: dict[str, Any],
    works: list[dict[str, Any]],
    history: dict[str, Any],
    source_person: dict[str, Any],
    faults: dict[str, Any],
    review_decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Record retained first/second/third-round scenarios without fake quality claims."""
    if not works:
        raise GateError("scenario coverage requires at least one published source")
    if not all(
        work.get("first_unit_id") and work.get("last_unit_id") and work.get("unit_count", 0) > 0
        for work in works
    ):
        raise GateError("scenario coverage could not prove first/last unit for every source")
    if not history.get("anchor_id") or not source_person.get("state_count", 0):
        raise GateError("scenario coverage lacks original-anchor or person-state evidence")
    if not any(work.get("event_ids") for work in works):
        raise GateError("scenario coverage lacks a published event anchor")
    if not {"resolution", "person_state"} <= {
        item.get("scope") for item in review_decisions
    }:
        raise GateError("scenario coverage did not observe resolution and person-state reviews")
    if not faults.get("chain_failure_no_partial", {}).get("passed"):
        raise GateError("scenario coverage lacks atomic failure evidence")
    if not faults.get("restart_preserves_published", {}).get("passed"):
        raise GateError("scenario coverage lacks restart/continue evidence")

    source_keys = [
        str(item.get("key") or item.get("title") or item.get("filename"))
        for item in loaded["pack"].get("sources", [])
    ]
    return {
        "chapter_first_and_last": {
            "status": "PASS",
            "sources": len(works),
            "units": [
                {
                    "stream_id": work["stream_id"],
                    "first_unit_id": work["first_unit_id"],
                    "last_unit_id": work["last_unit_id"],
                }
                for work in works
            ],
        },
        "aliases_and_identity": {
            "program_status": "PASS",
            "manual_status": "REQUIRED",
            "review_scopes": ["resolution"],
            "note": "machine checks review shape; a reviewer must judge aliases and identity",
        },
        "same_person_across_sources": {
            "program_status": "SOURCE_SCOPES_RECORDED",
            "manual_status": "REQUIRED",
            "source_keys": source_keys,
            "note": "cross-source identity is not inferred by the fixture",
        },
        "same_name_different_people": {
            "program_status": "NOT_ASSERTED",
            "manual_status": "REQUIRED",
            "note": "same-name separation is a content judgment, not a fixture assertion",
        },
        "state_phases": {
            "status": "PASS",
            "history_phase_id": history["phase_id"],
            "source_state_count": source_person["state_count"],
            "review_scopes": ["person_state", "narrative"],
        },
        "original_quotes_and_event_anchors": {
            "status": "PASS",
            "history_anchor_id": history["anchor_id"],
            "source_event_count": sum(len(work.get("event_ids", [])) for work in works),
        },
        "retry_cancellation_lease_takeover": {
            "status": "PROGRAM_TESTS",
            "faults": sorted(faults),
            "tests": [
                "apps/chronicle/worker/test_staged_chapter_pipeline_postgres.py",
                "apps/chronicle/worker/test_reading_pipeline_postgres.py",
                "apps/chronicle/worker/test_person_state_pipeline_postgres.py",
            ],
        },
        "atomic_publish": {
            "status": "PASS",
            "failure_evidence": "chain_failure_no_partial",
            "published_revision_count": len(works),
        },
        "manual_content_judgement": {
            "status": "REQUIRED_NOT_AUTOMATED",
            "read_full_chapters_and_outputs": True,
            "topics": [
                "translation fidelity",
                "aliases and identity",
                "same-name separation",
                "source disagreement",
                "state phase interpretation",
                "quote and event-anchor correctness",
            ],
        },
    }


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


def assert_time_contract(narrative_time: dict[str, Any]) -> None:
    """Check the semantic part of the reading time contract."""
    mode = narrative_time.get("mode")
    refs = narrative_time.get("event_refs")
    if not isinstance(refs, list):
        raise GateError("narrative_time.event_refs must be an array")
    if mode in ("events", "mixed") and not refs:
        raise GateError(f"narrative_time mode {mode!r} requires event_refs")
    if mode in ("unknown", "inherit") and refs:
        raise GateError(f"narrative_time mode {mode!r} must not carry event_refs")
    for field in (
        "status", "from_block_id", "observations", "year_key", "period_key",
        "year_label", "period_label", "precision", "continues_previous",
    ):
        if field not in narrative_time:
            raise GateError(f"narrative_time missing {field!r}")


def validate_scale_contract(base_url: str, scale: dict[str, Any]) -> dict[str, Any]:
    """Validate every DTO exposed by the explicitly synthetic scale stream."""
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
            errors = reading_contract.validate_reading_dto("context_entity_view", entity)
            if errors:
                raise GateError(f"synthetic context entity DTO invalid: {errors}")
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
    """Locate the explicit unknown-time, missing-context and missing-role cases."""
    units = public_json(
        base_url,
        f"/api/v1/public/reading-streams/{scale['stream_id']}/units"
        f"?catalog={scale['catalog_sha']}&limit=50",
    )["page"]["units"]
    negatives: dict[str, dict[str, Any]] = {}
    for index, unit in enumerate(units):
        if "unknown_time" not in negatives and unit["narrative_time"]["mode"] == "unknown":
            negatives["unknown_time"] = {
                "kind": "unknown_time", "stream_id": scale["stream_id"],
                "catalog_sha": scale["catalog_sha"], "unit_id": unit["unit_id"],
            }
        if (
            "missing_context" not in negatives
            and not unit.get("context_entities")
            and index > 0
            and units[index - 1].get("context_entities")
        ):
            negatives["missing_context"] = {
                "kind": "missing_context", "stream_id": scale["stream_id"],
                "catalog_sha": scale["catalog_sha"], "unit_id": unit["unit_id"],
                "previous_context_unit_id": units[index - 1]["unit_id"],
            }
        for entity in unit.get("context_entities", []):
            if "missing_role" not in negatives and not entity.get("event_roles"):
                negatives["missing_role"] = {
                    "kind": "missing_role", "stream_id": scale["stream_id"],
                    "catalog_sha": scale["catalog_sha"], "unit_id": unit["unit_id"],
                    "entity_ref": entity["entity_ref"],
                }
                break
    for kind in ("unknown_time", "missing_context", "missing_role"):
        if kind not in negatives:
            raise GateError(f"fixture data exposes no {kind!r} negative scenario")
    return [negatives[kind] for kind in ("unknown_time", "missing_context", "missing_role")]


def build_reading_browser_manifest(
    works: list[dict[str, Any]],
    *,
    base_url: str,
    scale: dict[str, Any],
    versions: list[dict[str, Any]],
    negatives: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": READING_BROWSER_MANIFEST_SCHEMA,
        "version": READING_BROWSER_MANIFEST_VERSION,
        "generated_by": "C3-T01",
        "base_url": base_url,
        "streams": [
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
        ],
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
        "budgets": {
            "active_to_sidebar_p95_ms": PERF_BUDGETS["person_region_p95_ms"],
            "restore_p95_ms": 250,
            "max_long_task_ms": PERF_BUDGETS["max_long_task_ms"],
            "mounted_max_units": PERF_BUDGETS["mounted_max_units"],
            "target_units": PERF_BUDGETS["target_units"],
            "target_groups": PERF_BUDGETS["target_groups"],
        },
    }


def validate_reading_browser_manifest(manifest: Any) -> dict[str, Any]:
    """Fail closed before the integrated reading browser driver starts."""
    if not isinstance(manifest, dict) or manifest.get("schema") != READING_BROWSER_MANIFEST_SCHEMA:
        raise GateError(
            f"reading browser manifest schema must be {READING_BROWSER_MANIFEST_SCHEMA!r}"
        )
    streams = manifest.get("streams")
    if not isinstance(streams, list) or not streams:
        raise GateError("reading browser manifest carries no streams")
    for stream in streams:
        for field in ("stream_id", "catalog_sha", "first_unit_id", "unit_count", "group_count"):
            if stream.get(field) in (None, ""):
                raise GateError(f"reading browser stream missing {field!r}")
        if len(str(stream["catalog_sha"])) != 64 or int(stream["unit_count"]) < 1:
            raise GateError("reading browser stream has an invalid catalog or unit count")
    scale = manifest.get("scale")
    if not isinstance(scale, dict) or not scale.get("stream_id"):
        raise GateError("reading browser manifest carries no synthetic scale stream")
    if int(scale.get("unit_count", 0)) < PERF_BUDGETS["target_units"]:
        raise GateError("reading browser scale stream is below the 5,000-unit target")
    if int(scale.get("group_count", 0)) < PERF_BUDGETS["target_groups"]:
        raise GateError("reading browser scale stream is below the 1,000-group target")
    if not isinstance(manifest.get("versions"), list) or not manifest["versions"]:
        raise GateError("reading browser manifest carries no content versions")
    negatives = manifest.get("negatives")
    if not isinstance(negatives, list):
        raise GateError("reading browser manifest carries no negative scenarios")
    kinds = {item.get("kind") for item in negatives if isinstance(item, dict)}
    for required in ("unknown_time", "missing_context", "missing_role"):
        if required not in kinds:
            raise GateError(f"reading browser manifest missing {required!r} negative")
        item = next(item for item in negatives if item.get("kind") == required)
        for field in ("stream_id", "catalog_sha", "unit_id"):
            if not item.get(field):
                raise GateError(f"reading negative {required!r} missing {field!r}")
    return manifest


def run_reading_browser_driver(
    manifest_path: Path, *, base_url: str, suite: str, output_dir: Path
) -> dict[str, Any]:
    script = REPO / "apps" / "chronicle" / "webapp" / "scripts" / "reading-flow-smoke.mjs"
    if not script.is_file():
        raise GateError(f"reading browser driver is missing: {script}")
    if not shutil.which("node"):
        raise GateError("node is required to run the reading browser driver")
    output_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "node", str(script), "--base-url", base_url,
            "--fixture-manifest", str(manifest_path), "--suite", suite,
            "--output", str(output_dir),
        ], cwd=REPO, text=True, capture_output=True,
    )
    (output_dir / "driver.log").write_text(
        result.stdout + "\n" + result.stderr, encoding="utf-8"
    )
    payload_path = output_dir / "result.json"
    payload: Any = None
    if payload_path.is_file():
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    if result.returncode != 0:
        raise GateError(
            f"reading-flow-smoke failed ({result.returncode}); see {output_dir}: "
            f"{(result.stdout + result.stderr)[-1200:]}"
        )
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise GateError(f"reading-flow-smoke did not report ok=true: {payload}")
    return payload


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
        "generated_by": "C3-T01",
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
    provider = staged_fixture.StagedFixtureProvider(free_port())
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
            project=default_gate_project("staged"),
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

        # Source chain: upload -> staged 0.4 production -> identity/phase review ->
        # atomic publish of catalog + chapters + reading index + manifest.
        works: list[dict[str, Any]] = []
        for upload in loaded["uploads"]:
            published = collect_published_work(
                base_url, publish_upload(base_url, auth, upload, evidence)
            )
            works.append(published)
            evidence.data["works"] = works
            evidence.checkpoint()

        # Keep a real second revision in the same document so the reading driver
        # proves catalog/version pinning through the current source path.
        version_source = evidence_dir / "staged-version-2.md"
        version_source.write_text(
            loaded["uploads"][0]["text"] + "\n\n版本二新增段落。\n", encoding="utf-8"
        )
        version = collect_published_work(
            base_url,
            publish_revision(
                base_url,
                auth,
                works[0]["document_id"],
                version_source,
                "staged-version-2",
                evidence,
            ),
        )
        works.append(version)
        evidence.data["works"] = works
        evidence.data["versions"] = [
            {
                "label": "v1",
                "catalog_sha": works[0]["catalog_sha"],
                "stream_id": works[0]["stream_id"],
            },
            {
                "label": "v2",
                "catalog_sha": version["catalog_sha"],
                "stream_id": version["stream_id"],
            },
        ]
        evidence.checkpoint()

        # Explicit comprehensive history job with both review gates.
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
                    "owning_module": "staged chapter publication/read API",
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

        evidence.data["scenario_coverage"] = build_scenario_coverage(
            loaded,
            works,
            history,
            source_person,
            evidence.data["faults"],
            evidence.data.get("review_decisions") or [],
        )
        evidence.checkpoint()

        # Synthetic scale stream + browser manifests. When a browser run is
        # requested, park one real source job on person-state and one real
        # synthesis job on facts so the mixed queue has genuinely open forms.
        scale = seed_scale_stream(stack, units=5000, groups=1000)
        evidence.data["scale"] = scale
        evidence.data["scale_contract"] = validate_scale_contract(base_url, scale)
        evidence.data["negatives"] = find_negatives(base_url, scale)

        reading_manifest = validate_reading_browser_manifest(
            build_reading_browser_manifest(
                works,
                base_url=base_url,
                scale=scale,
                versions=evidence.data["versions"],
                negatives=evidence.data["negatives"],
            )
        )
        reading_manifest_path = evidence_dir / "reading-fixture-manifest.json"
        write_json(reading_manifest_path, reading_manifest)
        person_manifest = validate_browser_manifest(
            build_browser_manifest(
                base_url=base_url,
                history=history,
                source_person=source_person,
                scale=scale,
                review_jobs={
                    "person_state_job_id": park_source_at_person_state(
                        base_url, auth, loaded["uploads"][0], evidence_dir
                    ),
                },
            )
        )
        person_manifest_path = evidence_dir / "person-state-fixture-manifest.json"
        write_json(person_manifest_path, person_manifest)
        evidence.data["browser_manifest"] = {
            "reading": {
                "path": str(reading_manifest_path),
                "schema": reading_manifest["schema"],
                "streams": len(reading_manifest["streams"]),
            },
            "person_state": {
                "path": str(person_manifest_path),
                "schema": person_manifest["schema"],
                "version": person_manifest["history"]["version"],
            },
        }

        if run_browser:
            reading_result = run_reading_browser_driver(
                reading_manifest_path,
                base_url=base_url,
                suite="all",
                output_dir=evidence_dir / "reading-browser",
            )
            person_result = run_browser_driver(
                person_manifest_path,
                base_url=base_url,
                suite="all",
                output_dir=evidence_dir / "person-browser",
                username=config["CHRONICLE_ADMIN_USER"],
                password=config["CHRONICLE_ADMIN_PASSWORD"],
            )
            evidence.data["browser"] = {
                "ok": bool(reading_result.get("ok") and person_result.get("ok")),
                "results": (reading_result.get("results") or [])
                + (person_result.get("results") or []),
                "reading": reading_result,
                "person_state": person_result,
            }
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
            "staged_0_4_source_to_acceptance": "PASS",
            "scenario_coverage": "PASS" if evidence.data.get("scenario_coverage") else "FAIL",
            "source_person_state_publish_chain": "PASS",
            "composite_history_two_review_chain": "PASS",
            "published_history_and_person_page": "PASS",
            "negative_faults": "PASS" if faults_ok else "FAIL",
            "scale_contract": "PASS" if evidence.data.get("scale_contract") else "FAIL",
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
            "this entry issues a READY handoff; live content execution remains an operator-controlled run"
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
            "python3 apps/chronicle/acceptance/staged_gate.py "
            f"--mode live --env-file {env_file} "
            f"--source-pack {pack_path} --evidence-dir {evidence_dir}"
        )
        evidence.data["live_handoff"] = {
            "steps": [
                "start an isolated Compose stack on a fresh CHRONICLE_DATA_DIR",
                "upload the frozen whole chapters through Studio and queue staged jobs",
                "resolve every identity and chapter_state_evidence review by hand",
                "explicitly select published sources and run the comprehensive job",
                "resolve the facts review and the prose review by hand",
                "read the published HistoryPage and independent person pages; record "
                "version/paragraph_id/phase_id and original anchors",
                "run person-state-flow-smoke.mjs against the running stack",
                "record the live content acceptance; fixture PASS is not proof",
            ],
            "provider_calls_during_preflight": 0,
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
        print(f"staged 0.4 gate: PASS: {evidence_dir / 'manifest.json'}")
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
    print(f"staged 0.4 gate: READY: {evidence_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GateError as exc:
        print(f"staged 0.4 gate: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
