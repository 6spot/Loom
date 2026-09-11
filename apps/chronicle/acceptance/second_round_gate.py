#!/usr/bin/env python3
"""Chronicle second-round continuous-reading automated gate (C2-R2-T16).

Unified thin orchestration entry for the second-round acceptance loop::

    python3 apps/chronicle/acceptance/second_round_gate.py \
        --mode fixture \
        --env-file /tmp/chronicle-second-round-test.env \
        --source-pack apps/chronicle/corpus/first-round/source-pack.json \
        --evidence-dir /tmp/chronicle-r2-offline

``fixture`` mode is a real, isolated offline chain: it plans the frozen
first-round source pack with the production ``chapter_plan`` entry, builds a
deterministic 0.2 whole-chapter reading fixture pack grounded verbatim in the
planned chapter text, runs the real joint chapter pipeline
(``worker.run_once`` with the explicit ``FixtureReadingChapterModel``) through
extract/assemble/resolve/publish against an isolated PostgreSQL 18 database,
and reads the published stream/units/groups/events back through the production
T07/T08 read entries. Fixture results are explicitly labelled non-live and can
never prove real content correctness.

``live`` mode performs the strict prechecks for a real-provider run (fixture
exclusion, complete provider identity, Compose config, interactive review) and
stops with a READY handoff for T17. It never calls a real provider and never
auto-decides review identity.

The gate reuses the ``gate_runtime`` lifecycle shared with the first-round
gate; it never writes product tables with raw SQL, and it never constructs a
successful result outside the product acceptance entries.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

GATE_SCHEMA = "chronicle.second-round-gate-evidence"
GATE_VERSION = "0.1"
BROWSER_MANIFEST_SCHEMA = "chronicle.reading-flow-fixture"
BROWSER_MANIFEST_VERSION = "0.1"
FIXTURE_DISCLAIMER = (
    "fixture mode is deterministic offline orchestration only; "
    "it is NOT live content proof and MUST NOT be cited as real "
    "translation/reading-annotation correctness evidence"
)
DEFAULT_CONTROL_URL = "postgresql://loom:loom@127.0.0.1:15432/loom_control"
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
    Evidence,
    GateError,
    IsolatedDatabase,
    candidate_commit,
    load_env_file,
    load_source_pack,
    require_live_config,
    safe_provider,
    sha256_text,
    verify_pack_manifest_hashes,
    write_json,
)

import chapter_contract  # noqa: E402
import chapter_plan  # noqa: E402
import control_plane  # noqa: E402
import fixture_model  # noqa: E402
import ingestion_worker as worker  # noqa: E402
import resolve_publish  # noqa: E402
from repository import ChronicleReadRepository  # noqa: E402

import router as read_router  # noqa: E402


# ---------------------------------------------------------------------------
# Boundary guards
# ---------------------------------------------------------------------------


def check_no_direct_product_writes() -> dict[str, Any]:
    """Prove this orchestrator never writes product rows with raw SQL.

    Product mutation must go through the worker/publish/read acceptance
    entries. Raw INSERT/UPDATE/DELETE/CREATE/DROP/ALTER statements are
    refused here. Statement-free ``psycopg`` use for isolated-database
    provisioning (owned by ``gate_runtime``) and read-only SELECTs is
    allowed.
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
    """Fixture mode never calls a live provider, so inject the exclusion."""
    if config.get("CHRONICLE_CHAPTER_MODEL", "").strip():
        raise GateError(
            "fixture mode refuses CHRONICLE_CHAPTER_MODEL; a fixture run must "
            "use the injected reading fixture provider, never a live model"
        )


def require_live_env(config: dict[str, str]) -> dict[str, Any]:
    """Strict live-provider preflight, shared rules plus the joint model."""
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
    parsed = urllib.parse.urlparse(config["CHRONICLE_MODEL_ENDPOINT"])
    if parsed.username is not None or parsed.password is not None:
        raise GateError("CHRONICLE_MODEL_ENDPOINT must not embed credentials")
    provider = safe_provider(config)
    provider["chapter_model"] = config["CHRONICLE_CHAPTER_MODEL"]
    return provider


# ---------------------------------------------------------------------------
# Fixture construction (deterministic, verbatim-grounded)
# ---------------------------------------------------------------------------


def pick_unique_mention(text: str, blocked: set[str]) -> str:
    """Find a short verbatim substring occurring exactly once in the text."""
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


def plan_upload(upload: dict[str, Any], revision_id: uuid.UUID) -> dict[str, Any]:
    """Plan one upload with the production chapter planner.

    The plan is bound to the revision identity created by the product, so the
    fixture pack and the worker replan produce the same chapter identities.
    """
    text = upload["text"]
    locator = {
        "revision_id": str(revision_id),
        "source_sha256": upload["sha256"],
        "normalized_sha256": sha256_text(text),
    }
    try:
        plan = chapter_plan.plan_chapters(
            text,
            locator,
            Path(upload["upload"]).name,
            limits=chapter_contract.ChapterLimits(),
        )
    except Exception as exc:  # noqa: BLE001 - product failures are gate failures
        raise GateError(f"plan_chapters failed for {upload['upload']!r}: {exc}") from exc
    return {"upload": upload, "plan": plan, "text": text}


def reading_fixture_pack(planned: dict[str, Any], source_title: str) -> dict[str, Any]:
    """Build a deterministic 0.2 reading fixture pack for one planned work."""
    plan = planned["plan"]
    text = planned["text"]
    used: set[str] = set()
    chapters: list[dict[str, Any]] = []
    limits = chapter_contract.ChapterLimits()
    for chapter in plan["chapters"]:
        request = chapter_plan.build_chapter_request(
            plan, chapter["chapter_index"], text, limits=limits
        )
        mention = pick_unique_mention(request["normalized_text"], used)
        used.add(mention)
        chapters.append(
            {
                "chapter_id": chapter["chapter_id"],
                "revision_id": plan["revision_id"],
                "source_title": source_title,
                "translation_text": f"fixture白話譯文（{mention}）非真實譯文",
                "entities": [{"mention": mention, "type": "person", "name": mention}],
                "event": {"type": "battle", "title": f"fixture事件（{mention}）"},
                "predicate": "affected",
            }
        )
    return {
        "schema": "chronicle.chapter-fixture-pack",
        "version": "0.1",
        "model_version": "c2r2-reading-gate",
        "chapters": chapters,
    }


def load_reading_fixture_model(pack: dict[str, Any], pack_path: Path) -> Any:
    write_json(pack_path, pack)
    return fixture_model.models_from_reading_chapter_fixture_pack(pack_path)


# ---------------------------------------------------------------------------
# Real offline chain (Python + PostgreSQL product entries)
# ---------------------------------------------------------------------------


def queue_work(
    database_url: str, upload: dict[str, Any]
) -> tuple[uuid.UUID, uuid.UUID]:
    import psycopg  # noqa: PLC0415

    with psycopg.connect(database_url) as conn:
        document_id = control_plane.create_document(
            conn, title=Path(upload["upload"]).name
        )
        revision_id, _ = control_plane.create_revision(
            conn,
            document_id=document_id,
            source_sha256=upload["sha256"],
            source_bytes=upload["bytes"],
            source_media_type="text/markdown",
            filename=Path(upload["upload"]).name,
        )
        job_id = control_plane.queue_job(conn, revision_id=revision_id)
        conn.commit()
    return job_id, revision_id


def run_work_chain(
    database_url: str,
    upload: dict[str, Any],
    *,
    stage_dir: Path,
    worker_id: str = "c2r2-gate",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Drive one work through the real chain to publication, then read it."""
    job_id, revision_id = queue_work(database_url, upload)
    planned = plan_upload(upload, revision_id)
    pack = reading_fixture_pack(
        planned, source_title=str(upload["upload"])
    )
    model = load_reading_fixture_model(
        pack, stage_dir / f"reading-fixture-{upload['sha256'][:12]}.json"
    )
    text = planned["text"]
    source_sha = upload["sha256"]
    claimed = worker.run_once(
        database_url,
        worker=worker_id,
        revision_source=lambda _job: (text, source_sha),
        chapter_model=model,
        chapter_limits=chapter_contract.ChapterLimits(),
        job_id=job_id,
    )
    if claimed is None:
        raise GateError(f"worker did not claim queued job {job_id}")
    _, outcome = claimed
    if outcome != "completed":
        raise GateError(f"reading chain did not complete: outcome={outcome!r}")
    result = read_published_stream(database_url, revision_id=revision_id, job_id=job_id)
    return result, planned


def _connect(database_url: str) -> Any:
    import psycopg  # noqa: PLC0415

    return psycopg.connect(database_url)


def _dispatch(repo: ChronicleReadRepository, path: str, query: str) -> dict[str, Any]:
    status, payload = read_router.dispatch(repo, "GET", path, query)
    if status != 200:
        raise GateError(f"read route {path}?{query} returned HTTP {status}: {payload}")
    return payload


def read_published_stream(
    database_url: str, *, revision_id: uuid.UUID, job_id: uuid.UUID
) -> dict[str, Any]:
    import psycopg  # noqa: PLC0415

    with psycopg.connect(database_url) as conn:
        catalog = resolve_publish.read_latest_catalog(conn)
        if catalog is None:
            raise GateError("publication produced no canonical catalog")
        catalog_sha = resolve_publish.sha256_json(catalog)
        row = conn.execute(
            """
            SELECT stream_id, unit_count, group_count
            FROM chronicle.reading_streams WHERE revision_id = %s
            """,
            (revision_id,),
        ).fetchone()
        if row is None:
            raise GateError("publication produced no reading stream")
        stream_id = str(row[0])
        event_rows = conn.execute(
            """
            SELECT DISTINCT canonical_event_id
            FROM chronicle.reading_event_occurrences WHERE stream_id = %s
            """,
            (row[0],),
        ).fetchall()
        event_ids = [str(item[0]) for item in event_rows]
        repo = ChronicleReadRepository(conn)
        actions: dict[str, Any] = {
            "job_id": str(job_id),
            "revision_id": str(revision_id),
            "catalog_sha": catalog_sha,
            "stream_id": stream_id,
            "unit_count": int(row[1]),
            "group_count": int(row[2]),
            "event_ids": sorted(event_ids),
        }
        actions["directory"] = _dispatch(
            repo, "/v0/reading-streams", f"catalog={catalog_sha}"
        )
        actions["detail"] = _dispatch(
            repo, f"/v0/reading-streams/{stream_id}", f"catalog={catalog_sha}"
        )
        actions["units"] = _dispatch(
            repo,
            f"/v0/reading-streams/{stream_id}/units",
            f"catalog={catalog_sha}&limit=50",
        )
        actions["groups"] = _dispatch(
            repo,
            f"/v0/reading-streams/{stream_id}/groups",
            f"catalog={catalog_sha}&limit=100",
        )
    _assert_units_reassemble(actions, database_url=database_url)
    _assert_locate(actions, database_url=database_url)
    if event_ids:
        _assert_event_views(actions, database_url=database_url)
    return actions


def _assert_units_reassemble(actions: dict[str, Any], *, database_url: str) -> None:
    units = actions["units"]["page"]["units"]
    if not units:
        raise GateError("reading stream exposed no units")
    if actions["directory"]["page"]["streams"] == []:
        raise GateError("reading directory is empty after publication")
    with _connect(database_url) as db:
        for unit in units:
            joined = "".join(
                segment.get("text", "")
                for segment in unit.get("segments", [])
                if "text" in segment
            )
            row = db.execute(
                """
                SELECT segments FROM chronicle.reading_units
                WHERE stream_id = %s AND unit_id = %s
                """,
                (uuid.UUID(actions["stream_id"]), unit["unit_id"]),
            ).fetchone()
            if row is None:
                raise GateError(f"unit {unit['unit_id']} missing from the store")
            stored = "".join(
                segment.get("text", "")
                for segment in row[0]
                if "text" in segment
            )
            if joined != stored or not joined:
                raise GateError(
                    f"unit {unit['unit_id']} API segments do not reassemble the stored text"
                )


def _assert_locate(actions: dict[str, Any], *, database_url: str) -> None:
    first = actions["units"]["page"]["units"][0]
    located = _dispatch(
        ChronicleReadRepository(_connect(database_url)),
        f"/v0/reading-streams/{actions['stream_id']}/locate",
        f"catalog={actions['catalog_sha']}&unit_id={first['unit_id']}&limit=5",
    )
    if located["page"]["units"][0]["unit_id"] != first["unit_id"]:
        raise GateError("locate did not return the exact requested unit")
    status, payload = read_router.dispatch(
        ChronicleReadRepository(_connect(database_url)),
        "GET",
        f"/v0/reading-streams/{actions['stream_id']}/locate",
        f"catalog={actions['catalog_sha']}&unit_id=ru_{'0' * 24}&limit=5",
    )
    if status != 404:
        raise GateError(
            f"unknown locator must fail closed with 404, got {status}: {payload}"
        )
    actions["locate"] = located
    actions["unknown_locator_status"] = status


def _assert_event_views(actions: dict[str, Any], *, database_url: str) -> None:
    event_id = actions["event_ids"][0]
    repo = ChronicleReadRepository(_connect(database_url))
    actions["event_preview"] = _dispatch(
        repo,
        f"/v0/reading-events/{event_id}/preview",
        f"catalog={actions['catalog_sha']}",
    )
    actions["event_targets"] = _dispatch(
        repo,
        f"/v0/reading-events/{event_id}/targets",
        f"catalog={actions['catalog_sha']}&limit=20",
    )


# ---------------------------------------------------------------------------
# Fault injection (fail-closed proofs)
# ---------------------------------------------------------------------------


def _unknown_uuid7() -> uuid.UUID:
    """A syntactically valid UUIDv7 that no fixture ever publishes."""
    raw = bytearray(uuid.uuid4().bytes)
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(raw))


def fault_checks(
    database_url: str, planned: dict[str, Any], *, stage_dir: Path
) -> dict[str, Any]:
    import psycopg  # noqa: PLC0415

    faults: dict[str, Any] = {}
    plan = planned["plan"]
    text = planned["text"]
    limits = chapter_contract.ChapterLimits()

    # F1: a fixture pack whose chapter identity drifted is refused before any
    # model call can produce a candidate.
    bogus = reading_fixture_pack(planned, source_title="fixture")
    bogus["chapters"] = [
        dict(item, chapter_id=f"ch_{index:024x}")
        for index, item in enumerate(bogus["chapters"])
    ]
    bogus_model = load_reading_fixture_model(bogus, stage_dir / "drifted-pack.json")
    request = chapter_plan.build_chapter_request(plan, 0, text, limits=limits)
    try:
        bogus_model.build_for_request(request)
    except Exception as exc:  # noqa: BLE001
        faults["fixture_identity_drift"] = {"passed": True, "error": str(exc)[:200]}
    else:
        raise GateError("drifted fixture pack must fail closed")

    # F2: a plan whose chapter content hash drifted can never publish and
    # leaks no partial reading stream.
    with psycopg.connect(database_url) as conn:
        before = conn.execute(
            "SELECT count(*) FROM chronicle.reading_streams"
        ).fetchone()[0]
        drifted = copy.deepcopy(plan)
        drifted["chapters"][0]["content_sha256"] = "1" * 64
        try:
            resolve_publish.publish_chapters(
                conn, job_id=uuid.uuid4(), worker="fault", chapter_plan=drifted
            )
        except Exception as exc:  # noqa: BLE001
            faults["drifted_plan_refused"] = {"passed": True, "error": str(exc)[:200]}
        else:
            raise GateError("drifted chapter plan must fail closed")
        after = conn.execute(
            "SELECT count(*) FROM chronicle.reading_streams"
        ).fetchone()[0]
        if after != before:
            raise GateError("failed publish leaked a reading stream")

    # F3: an unknown stream is not silently replaced by the newest snapshot.
    with psycopg.connect(database_url) as conn:
        repo = ChronicleReadRepository(conn)
        status, payload = read_router.dispatch(
            repo, "GET", f"/v0/reading-streams/{_unknown_uuid7()}", ""
        )
        if status != 404:
            raise GateError(
                f"unknown stream must fail closed with 404, got {status}: {payload}"
            )
        faults["unknown_stream_refused"] = {"passed": True, "status": status}

    # F4: a missing fixture pack is refused, never treated as empty success.
    try:
        fixture_model.models_from_reading_chapter_fixture_pack(
            stage_dir / "no-such-pack.json"
        )
    except Exception as exc:  # noqa: BLE001
        faults["missing_fixture_refused"] = {"passed": True, "error": str(exc)[:200]}
    else:
        raise GateError("missing fixture pack must fail closed")
    return faults


# ---------------------------------------------------------------------------
# Browser manifest + driver
# ---------------------------------------------------------------------------


def build_browser_manifest(
    works: list[dict[str, Any]], *, base_url: str | None
) -> dict[str, Any]:
    streams = [
        {
            "stream_id": work["stream_id"],
            "catalog_sha": work["catalog_sha"],
            "source_title": work.get("source_title"),
            "unit_count": work["unit_count"],
            "group_count": work["group_count"],
            "first_unit_id": work["first_unit_id"],
            "event_ids": work["event_ids"],
        }
        for work in works
    ]
    return {
        "schema": BROWSER_MANIFEST_SCHEMA,
        "version": BROWSER_MANIFEST_VERSION,
        "generated_by": "C2-R2-T16",
        "base_url": base_url,
        "streams": streams,
        "viewports": list(VIEWPORTS),
        "budgets": dict(PERF_BUDGETS),
        "performance": {
            "synthetic": True,
            "status": "not_measured",
            "target_units": PERF_BUDGETS["target_units"],
            "target_groups": PERF_BUDGETS["target_groups"],
            "reason": (
                "the 5,000-unit/1,000-group synthetic set must be measured on "
                "the running real stack by the performance browser suite; a "
                "missing set must fail the gate, not silently pass"
            ),
        },
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
    return manifest


def run_browser_driver(
    manifest_path: Path, *, base_url: str, suite: str, output_dir: Path
) -> dict[str, Any]:
    script = REPO / "apps" / "chronicle" / "webapp" / "scripts" / "reading-flow-smoke.mjs"
    if not script.is_file():
        raise GateError(f"browser driver is missing: {script}")
    if not base_url:
        raise GateError("browser driver requires a running stack base URL")
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
    payload_path = output_dir / "result.json"
    payload: Any = None
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
# Fixture mode
# ---------------------------------------------------------------------------


def run_fixture(
    env_file: Path,
    pack_path: Path,
    evidence_dir: Path,
    argv: list[str],
    *,
    allow_dirty: bool,
    control_url: str,
    base_url: str | None,
    run_browser: bool,
    browser_required: bool,
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
    stage_dir = evidence_dir / "fixture"
    stage_dir.mkdir(parents=True, exist_ok=True)
    database: IsolatedDatabase | None = None
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
        evidence.checkpoint()

        database = IsolatedDatabase(control_url)
        database.create()
        database_url = database.database_url or ""
        evidence.data["database"] = {
            "control_host": control_url.split("@")[-1],
            "isolated_name": database.name,
            "migrations": "apps/chronicle/persistence/migrations",
        }

        works: list[dict[str, Any]] = []
        first_planned: dict[str, Any] | None = None
        for upload in loaded["uploads"]:
            result, planned = run_work_chain(
                database_url, upload, stage_dir=stage_dir
            )
            if first_planned is None:
                first_planned = planned
            result["source_title"] = upload["work"] or Path(upload["upload"]).name
            result["first_unit_id"] = result["units"]["page"]["units"][0]["unit_id"]
            works.append(result)
            evidence.data["works"] = works
            evidence.checkpoint()

        if first_planned is None:
            raise GateError("source pack produced no planned work")

        evidence.data["faults"] = fault_checks(
            database_url, first_planned, stage_dir=stage_dir
        )
        evidence.checkpoint()

        manifest = validate_browser_manifest(
            build_browser_manifest(works, base_url=base_url)
        )
        manifest_path = evidence_dir / "browser-fixture-manifest.json"
        write_json(manifest_path, manifest)
        evidence.data["browser_manifest"] = {
            "path": str(manifest_path),
            "schema": manifest["schema"],
            "streams": len(manifest["streams"]),
        }

        if run_browser and base_url:
            evidence.data["browser"] = run_browser_driver(
                manifest_path,
                base_url=base_url,
                suite="all",
                output_dir=evidence_dir / "browser",
            )
        elif browser_required:
            raise GateError(
                "a browser run was required but no --base-url was supplied; "
                "start the real Rust/Python stack and re-run"
            )
        else:
            evidence.data["browser"] = {
                "ran": False,
                "reason": "no --base-url supplied; browser suite not exercised",
            }
        evidence.data["performance"] = {
            "synthetic": True,
            "status": "not_measured",
            "target_units": PERF_BUDGETS["target_units"],
            "target_groups": PERF_BUDGETS["target_groups"],
            "budgets": dict(PERF_BUDGETS),
            "reason": (
                "the 5,000-unit/1,000-group performance set must be measured "
                "on the running real stack by the performance browser suite; "
                "record it or keep the task incomplete"
            ),
        }
        evidence.data["criteria"] = {
            "real_stack_offline_chain": "PASS",
            "negative_faults": (
                "PASS"
                if all(item.get("passed") for item in evidence.data["faults"].values())
                else "FAIL"
            ),
            "browser_interaction": (
                "PASS" if evidence.data["browser"].get("ok") else "NOT_RUN"
            ),
            "performance_budget": "NOT_MEASURED",
        }
        return evidence.finish("PASS")
    except GateError as exc:
        evidence.fail(str(exc))
        raise
    finally:
        if database is not None:
            database.drop()


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
                "run the 0.2 reading chain with the live joint chapter model",
                "resolve every blocking review interactively in Studio",
                "run reading-flow-smoke.mjs against the running Rust/Python stack",
                "record the T17 content acceptance; fixture PASS is not proof",
            ],
            "provider_calls_by_t16": 0,
            "stack_lifecycle": (
                "the T17 operator starts the isolated stack through "
                "gate_runtime.ComposeStack; this handoff never leaves a "
                "half-started stack"
            ),
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
        "--control-url",
        default=None,
        help="PostgreSQL 18 control URL (defaults to LOOM_TEST_POSTGRES_URL)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="running Rust front base URL for the browser driver",
    )
    parser.add_argument(
        "--skip-browser",
        action="store_true",
        help="fixture only: do not run the browser driver",
    )
    parser.add_argument(
        "--browser-required",
        action="store_true",
        help="fixture only: fail unless the browser driver runs",
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
        control_url = (
            args.control_url
            or os.environ.get("LOOM_TEST_POSTGRES_URL")
            or DEFAULT_CONTROL_URL
        )
        evidence = run_fixture(
            env_file,
            pack_path,
            evidence_dir,
            full_argv,
            allow_dirty=args.allow_dirty,
            control_url=control_url,
            base_url=args.base_url,
            run_browser=not args.skip_browser,
            browser_required=args.browser_required,
        )
        print(f"second-round gate: PASS evidence={evidence_dir / 'manifest.json'}")
        print(
            f"works={len(evidence.get('works', []))} "
            f"faults={len(evidence.get('faults', {}))} mode=fixture (NOT live proof)"
        )
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
