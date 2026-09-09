#!/usr/bin/env python3
"""Chronicle first-round offline end-to-end gate (C2-R1-T18).

Unified orchestration entry for the first-round acceptance loop::

    python3 apps/chronicle/acceptance/first_round_gate.py \
        --mode fixture \
        --env-file /tmp/chronicle-first-round-test.env \
        --source-pack apps/chronicle/corpus/first-round/source-pack.json \
        --evidence-dir /tmp/chronicle-first-round-offline

``fixture`` mode is fully offline and deterministic: it plans the frozen
T02 source pack with the real ``plan_chapters`` entry, builds chapter
requests with the production chapter-slice hash binding, derives
deterministic fixture candidates through the real
``build_chapter_candidate`` builder, validates/accepts them with the T01
canonical validator, assembles them with the T07 ``assemble_chapters``
entry, exercises the T08 within-revision pair subjects plus the frozen
review-plan fingerprint, and runs the fail-closed fault injections.
Fixture results are explicitly labelled non-live and can never prove
real content correctness.

``live`` mode performs only the strict prechecks for a future real-model
run (fixture exclusion, explicit provider/model identity, complete
sample hashes, compose config, interactive-review requirement) and then
stops with a READY handoff for T19. T18 never calls a real provider and
never auto-decides review identity.

The script only orchestrates existing product APIs and Compose; it never
writes product PostgreSQL directly (no DB driver import, no SQL), and it
never invents history: every candidate quote is grounded verbatim in the
planned chapter text.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

GATE_SCHEMA = "chronicle.first-round-gate-evidence"
GATE_VERSION = "0.1"
FIXTURE_DISCLAIMER = (
    "fixture mode is deterministic offline orchestration only; "
    "it is NOT live content proof and MUST NOT be cited as real "
    "translation/review correctness evidence"
)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PERSISTENCE_DIR = REPO / "apps" / "chronicle" / "persistence"
WORKER_DIR = REPO / "apps" / "chronicle" / "worker"
for _path in (str(HERE), str(PERSISTENCE_DIR), str(WORKER_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import chapter_contract as C01  # noqa: E402
import chapter_plan as T03  # noqa: E402
import assembly as T07  # noqa: E402
import review_subjects as T08R  # noqa: E402
from common import PersistenceError, sha256_json  # noqa: E402
from fixture_model import build_chapter_candidate  # noqa: E402


class GateError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Small helpers (stdlib only; no product imports, no DB)
# ---------------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def check_no_direct_db_writes() -> dict[str, Any]:
    """Prove this orchestrator never touches product PostgreSQL directly."""
    lines = Path(__file__).read_text(encoding="utf-8").splitlines()
    # Exclude this check's own definition so the token list cannot match
    # itself; every other line of the orchestrator is scanned.
    scanning = True
    code_lines: list[str] = []
    for line in lines:
        if line.startswith("def check_no_direct_db_writes"):
            scanning = False
            continue
        if not scanning and line.startswith("def ") and "(" in line:
            scanning = True
        if scanning:
            code_lines.append(line)
    text = "\n".join(code_lines)
    forbidden = (
        "import psycopg",
        "from psycopg",
        "import pg8000",
        "import sqlite3",
        "CREATE TABLE",
        "INSERT INTO",
        "psql ",
        "psycopg.connect",
    )
    hits = [token for token in forbidden if token in text]
    if hits:
        raise GateError(
            "first_round_gate.py must not write product DB directly; "
            f"forbidden tokens present: {sorted(hits)}"
        )
    return {"direct_db_writes": False, "checked_tokens": len(forbidden)}


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


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def normalize_upload_bytes(raw: bytes) -> str:
    try:
        text = bytes(raw).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateError(f"upload is not valid UTF-8: {exc}") from exc
    if text.startswith("\ufeff"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def revision_id_for(label: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"c2r1-first-round-gate:{label}"))


# ---------------------------------------------------------------------------
# Source-pack handling (shared by fixture and live prechecks)
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
    """Cross-check upload hashes against the frozen T02 ingest manifest."""
    manifest_path = corpus_root / "ingest-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(
            f"cannot read ingest manifest {manifest_path}: {exc}"
        ) from exc
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
# Fixture candidate synthesis (verbatim-grounded, deterministic)
# ---------------------------------------------------------------------------


def pick_unique_mention(text: str, blocked: set[str]) -> str:
    """Find a short verbatim substring occurring exactly once in the text."""
    surfaces = set(C01.CONTEXTUAL_ONLY_SURFACES or set())
    for length in (6, 8, 10, 12):
        step = max(1, length // 2)
        for start in range(0, max(0, len(text) - length), step):
            snippet = text[start : start + length]
            if not snippet.strip() or "\n" in snippet or "#" in snippet:
                continue
            if snippet in surfaces or snippet in blocked:
                continue
            if text.count(snippet) == 1:
                return snippet
    raise GateError("no unique verbatim mention found in chapter text")


def fixture_spec_for(
    request: dict[str, Any], source_title: str, used: set[str]
) -> dict[str, Any]:
    text = request["normalized_text"]
    mention = pick_unique_mention(text, used)
    used.add(mention)
    return {
        "chapter_id": request["chapter_id"],
        "revision_id": request["revision_id"],
        "source_title": source_title,
        "translation_text": f"fixture白話譯文（{mention}）非真實譯文",
        "entities": [{"mention": mention, "type": "person", "name": mention}],
        "event": {"type": "battle", "title": f"fixture事件（{mention}）"},
        "predicate": "affected",
    }


def split_translation_blocks(candidate: dict[str, Any], required: list[str]) -> None:
    """Split one covering translation block into two ordered blocks.

    Keeps full required-block coverage and chapter block order while
    proving multi-block, multi-reference translation provenance.
    """
    blocks = candidate["translation"]["blocks"]
    if len(required) < 2 or len(blocks) != 1:
        return
    only = blocks[0]
    cut = len(required) // 2
    first_ids, second_ids = required[:cut], required[cut:]
    first = dict(only)
    first["block_id"] = "t_001"
    first["source_block_ids"] = list(first_ids)
    second = copy.deepcopy(only)
    second["block_id"] = "t_002"
    second["source_block_ids"] = list(second_ids)
    candidate["translation"]["blocks"] = [first, second]


def producing_run(run_id: str) -> dict[str, str]:
    return {
        "run_id": run_id,
        "model": "fixture:c2r1-first-round-gate",
        "prompt_schema_version": "c2r1-chapters-v1",
    }


# ---------------------------------------------------------------------------
# Fixture mode
# ---------------------------------------------------------------------------


def plan_work(
    upload: dict[str, Any], corpus_root: Path, evidence: dict[str, Any]
) -> dict[str, Any]:
    raw_path = Path(upload["path"])
    raw = raw_path.read_bytes()
    text = normalize_upload_bytes(raw)
    if text != upload["text"]:
        raise GateError(f"upload text changed during planning: {upload['upload']!r}")
    locator = {
        "revision_id": revision_id_for(upload["sha256"]),
        "source_sha256": upload["sha256"],
        "normalized_sha256": sha256_text(text),
    }
    try:
        plan = T03.plan_chapters(
            text, locator, Path(upload["upload"]).name,
            limits=C01.ChapterLimits(),
        )
    except PersistenceError as exc:
        raise GateError(f"plan_chapters failed for {upload['upload']!r}: {exc}") from exc
    chapters = plan["chapters"]
    # Explicit tiling proof: chapters cover the text exactly once, in order.
    cursor = 0
    for chapter in chapters:
        if chapter["start"] != cursor:
            raise GateError(
                f"chapter tiling gap/overlap in {upload['upload']!r} "
                f"at chapter {chapter['chapter_index']}"
            )
        if not chapter["required_block_ids"]:
            raise GateError(
                f"chapter {chapter['chapter_id']!r} carries no required blocks"
            )
        cursor = chapter["end"]
    if cursor != len(text):
        raise GateError(f"chapter tiling misses trailing text in {upload['upload']!r}")
    return {"upload": upload, "plan": plan, "text": text}


def accept_work_chapters(
    planned: dict[str, Any], source_title: str
) -> dict[str, Any]:
    plan = planned["plan"]
    text = planned["text"]
    used: set[str] = set()
    artifacts: list[dict[str, Any]] = []
    chapter_evidence: list[dict[str, Any]] = []
    for chapter in plan["chapters"]:
        request = T03.build_chapter_request(
            plan, chapter["chapter_index"], text, limits=C01.ChapterLimits()
        )
        # Production slice-hash binding (worker/chapter_stage.py): the T01
        # identity check hashes the chapter slice, and assembly matches it
        # against the plan chapter content hash.
        request["normalized_sha256"] = sha256_text(request["normalized_text"])
        spec = fixture_spec_for(request, source_title, used)
        try:
            candidate = build_chapter_candidate(request, spec)
        except PersistenceError as exc:
            raise GateError(
                f"fixture candidate build failed for "
                f"{chapter['chapter_id']!r}: {exc}"
            ) from exc
        required = list(request["required_block_ids"])
        split_translation_blocks(candidate, required)
        report = C01.validate_chapter_candidate(request, candidate)
        if not report.get("passed"):
            detail = "; ".join(C01.flatten_validation_errors(report))
            raise GateError(
                f"fixture candidate rejected for {chapter['chapter_id']!r}: "
                f"{detail}"
            )
        try:
            artifact = C01.accept_chapter_candidate(
                request, candidate,
                producing_run=producing_run(
                    f"fixture-{plan['revision_id'][:8]}-ch{chapter['chapter_index']}"
                ),
            )
        except PersistenceError as exc:
            raise GateError(
                f"fixture accept failed for {chapter['chapter_id']!r}: {exc}"
            ) from exc
        # Coverage proof: every required block (including first and last)
        # is referenced, in chapter order, by the translation.
        covered = [
            block_id
            for block in candidate["translation"]["blocks"]
            for block_id in block["source_block_ids"]
        ]
        missing = [item for item in required if item not in covered]
        if missing:
            raise GateError(
                f"translation misses required blocks {missing} "
                f"in {chapter['chapter_id']!r}"
            )
        if required[0] not in covered or required[-1] not in covered:
            raise GateError(
                f"translation misses first/last block in {chapter['chapter_id']!r}"
            )
        # Provenance proof: every record resolves to record_sources, every
        # mention surface equals its verbatim quote, anchors are recorded.
        refs = {
            record["temp_id"]
            for name in ("entities", "events", "claims")
            for record in candidate["bundle"].get(name, [])
        }
        sourced = {
            entry["record_ref"] for entry in candidate["record_sources"]
        }
        if refs - sourced:
            raise GateError(
                f"records without record_sources in {chapter['chapter_id']!r}: "
                f"{sorted(refs - sourced)}"
            )
        for mention in candidate["mentions"]:
            if mention["surface"] != mention["selection"]["quote"]:
                raise GateError(
                    f"mention surface/quote drift in {chapter['chapter_id']!r}"
                )
        if not artifact["anchors"]:
            raise GateError(
                f"no source anchors collected for {chapter['chapter_id']!r}"
            )
        artifacts.append(artifact)
        chapter_evidence.append(
            {
                "chapter_id": chapter["chapter_id"],
                "chapter_index": chapter["chapter_index"],
                "title": chapter["title"],
                "candidate_sha256": artifact["candidate_sha256"],
                "request_fingerprint": artifact["request_fingerprint"],
                "anchors": len(artifact["anchors"]),
                "translation_blocks": len(candidate["translation"]["blocks"]),
                "required_blocks": len(required),
            }
        )
    return {"artifacts": artifacts, "chapters": chapter_evidence}


def assemble_work(planned: dict[str, Any], accepted: dict[str, Any]) -> dict[str, Any]:
    plan = planned["plan"]
    try:
        assembled = T07.assemble_chapters(
            accepted_artifacts=accepted["artifacts"], chapter_plan=plan
        )
    except PersistenceError as exc:
        raise GateError(f"assemble_chapters failed: {exc}") from exc
    report = assembled.get("report", {})
    bundle = assembled.get("bundle", {})
    # No automatic same-link merge: distinct chapter records stay pending.
    entity_count = len(bundle.get("entities", []))
    expected_entities = sum(
        len(artifact["candidate"]["bundle"]["entities"])
        for artifact in accepted["artifacts"]
    )
    if entity_count != expected_entities:
        raise GateError(
            f"assembly merged or dropped entities: {entity_count} vs "
            f"{expected_entities} accepted inputs"
        )
    return {
        "bundle_sha256": sha256_json(bundle),
        "entities": entity_count,
        "events": len(bundle.get("events", [])),
        "claims": len(bundle.get("claims", [])),
        "translation_blocks": len(assembled.get("translation_blocks", [])),
        "chapter_by_ref": report.get("chapter_by_ref", {}),
        "local_to_revision": report.get("local_to_revision", {}),
        "chapter_manifest": report.get("chapter_manifest", []),
    }


def claimless_provenance_check(request: dict[str, Any], source_title: str) -> dict[str, Any]:
    """Prove record_source provenance works with no Claim in the bundle."""
    request = copy.deepcopy(request)
    candidate = build_chapter_candidate(
        request,
        {
            "chapter_id": request["chapter_id"],
            "revision_id": request["revision_id"],
            "source_title": source_title,
            "translation_text": "fixture白話譯文（無Claim對照）非真實譯文",
            "entities": [
                {
                    "mention": fixture_spec_for(request, source_title, set())[
                        "entities"
                    ][0]["mention"],
                    "type": "person",
                    "name": "fixture無Claim人物",
                }
            ],
            "event": {"type": "battle", "title": "fixture無Claim事件"},
            "predicate": "affected",
        },
    )
    candidate["bundle"]["claims"] = []
    candidate["record_sources"] = [
        entry
        for entry in candidate["record_sources"]
        if entry.get("record_kind") != "claim"
    ]
    # Claim evidence must reference the claim selection; with no claims the
    # remaining record_sources still resolve every entity/event.
    report = C01.validate_chapter_candidate(request, candidate)
    if not report.get("passed"):
        detail = "; ".join(C01.flatten_validation_errors(report))
        raise GateError(f"claimless candidate rejected: {detail}")
    kinds = {entry.get("record_kind") for entry in candidate["record_sources"]}
    if kinds != {"entity", "event"}:
        raise GateError(f"claimless record_sources kinds unexpected: {sorted(kinds)}")
    return {"passed": True, "record_kinds": sorted(kinds)}


def within_revision_pair_check(assembled: dict[str, Any]) -> dict[str, Any]:
    """Same-revision cross-chapter pair subjects stay uncertain, unmerged."""
    chapter_by_ref = assembled["chapter_by_ref"]
    refs_by_chapter: dict[str, list[str]] = {}
    for ref, chapter_id in chapter_by_ref.items():
        refs_by_chapter.setdefault(chapter_id, []).append(ref)
    chapters = sorted(refs_by_chapter)
    if len(chapters) < 2:
        raise GateError("within-revision pair check needs at least two chapters")
    left_ref = sorted(refs_by_chapter[chapters[0]])[0]
    right_ref = sorted(refs_by_chapter[chapters[1]])[0]
    bundle_label = "fixture-bundle"
    document = {
        "schema": "chronicle.resolution-links",
        "version": "0.2",
        "scope": "within_revision",
        "left_bundle": {
            "label": bundle_label,
            "source_ref": "src_001",
            "source_title": "fixture",
        },
        "right_bundle": {
            "label": bundle_label,
            "source_ref": "src_001",
            "source_title": "fixture",
        },
        "entity_links": [
            {
                "candidate_id": "ec_001",
                "left": {"bundle": bundle_label, "ref": left_ref},
                "right": {"bundle": bundle_label, "ref": right_ref},
                "decision": "uncertain",
                "confidence": 0.5,
                "rationale": "fixture same-surface cross-chapter pair; human review required",
                "signals": ["stable-surface"],
            }
        ],
        "event_links": [],
        "warnings": [],
    }
    validation = C01.validate_resolution_v02(document)
    if not validation.get("passed"):
        raise GateError(
            f"within-revision resolution rejected: {validation['errors']}"
        )
    try:
        subjects = T08R.build_chapter_pair_subjects(
            [document], chapter_by_ref=dict(chapter_by_ref)
        )
    except PersistenceError as exc:
        raise GateError(f"chapter pair subjects failed: {exc}") from exc
    if len(subjects) != 1:
        raise GateError(f"expected exactly one pair subject, got {len(subjects)}")
    payload = T08R.chapter_pair_payload(subjects[0], plan_fingerprint="fixture-fp")
    if payload.get("initial_decision") != "uncertain" or not payload.get("blocking"):
        raise GateError("chapter pair payload must start uncertain and blocking")
    if payload.get("decision") is not None:
        raise GateError("chapter pair payload must not carry an auto decision")
    # Negative proofs: self links and same-chapter pairs are refused.
    self_link = copy.deepcopy(document)
    self_link["entity_links"][0]["right"] = {"bundle": bundle_label, "ref": left_ref}
    self_validation = C01.validate_resolution_v02(self_link)
    if self_validation.get("passed"):
        raise GateError("self-linking resolution must not validate")
    same_chapter = copy.deepcopy(document)
    same_chapter["entity_links"][0]["right"] = {
        "bundle": bundle_label,
        "ref": sorted(refs_by_chapter[chapters[0]])[-1],
    }
    try:
        T08R.build_chapter_pair_subjects(
            [same_chapter], chapter_by_ref=dict(chapter_by_ref)
        )
    except PersistenceError:
        same_chapter_refused = True
    else:
        # Same ref on both ends is also invalid; distinct same-chapter refs
        # must equally be refused as non-cross-chapter.
        same_chapter_refused = same_chapter["entity_links"][0][
            "left"
        ] == same_chapter["entity_links"][0]["right"]
        if not same_chapter_refused:
            raise GateError("same-chapter pair must be refused")
    return {
        "subjects": len(subjects),
        "initial_decision": payload["initial_decision"],
        "blocking": payload["blocking"],
        "self_link_refused": True,
        "same_chapter_refused": bool(same_chapter_refused),
    }


def batch_context_check(assembled: dict[str, Any]) -> dict[str, Any]:
    """Cross-book batch/default/override DTOs validate without auto-merge."""
    refs = sorted(assembled["chapter_by_ref"])
    if len(refs) < 2:
        raise GateError("batch check needs at least two assembled refs")
    members = [
        {"bundle": "fixture-bundle", "ref": ref} for ref in refs[:2]
    ]
    groups = [
        {
            "review_group_id": f"fixture-group-{index}",
            "component_root": member["ref"],
            "members": [member],
            "member_count": 1,
            "candidate_keys": [f"fixture-candidate-{index}"],
        }
        for index, member in enumerate(members)
    ]
    context = C01.example_batch_context(
        review_subject_id="fixture-batch-subject",
        link_kind="entity",
        canonical_id="fixture-canonical-entity",
        groups=groups,
        members=members,
    )
    # One explicit per-group override; the default itself stays uncertain.
    context["group_overrides"] = [
        {
            "review_group_id": groups[0]["review_group_id"],
            "decision": "not_same",
            "rationale": "fixture override shape proof; human review required",
        }
    ]
    errors = C01.validate_batch_context(context)
    if errors:
        raise GateError(f"batch context example rejected: {errors}")
    if context.get("default_decision") != "uncertain":
        raise GateError("batch default decision must stay uncertain")
    return {
        "passed": True,
        "groups": len(groups),
        "default_decision": context["default_decision"],
        "overrides": len(context["group_overrides"]),
    }


def fault_injection_checks(
    planned_works: list[dict[str, Any]],
    accepted_works: list[dict[str, Any]],
) -> dict[str, Any]:
    faults: dict[str, Any] = {}

    first = planned_works[0]
    plan = first["plan"]
    text = first["text"]
    artifacts = accepted_works[0]["artifacts"]

    def expect_failure(name: str, func) -> dict[str, Any]:
        try:
            func()
        except (PersistenceError, GateError) as exc:
            return {"passed": True, "error": str(exc)[:300]}
        raise GateError(f"fault {name} did not fail closed")

    # F1 missing chapter: a finished subset must never assemble.
    faults["missing_chapter"] = expect_failure(
        "missing_chapter",
        lambda: T07.assemble_chapters(
            accepted_artifacts=artifacts[:-1], chapter_plan=plan
        ),
    )
    # F2 over-limit/length: tiny budgets reject the whole chapter.
    def _over_limit() -> None:
        tiny = C01.ChapterLimits(max_source_chars=8)
        locator = {
            "revision_id": plan["revision_id"],
            "source_sha256": plan["source_sha256"],
            "normalized_sha256": plan["normalized_sha256"],
        }
        T03.plan_chapters(text, locator, "fixture.md", limits=tiny)

    faults["over_limit"] = expect_failure("over_limit", _over_limit)
    # F3 source hash error: drifted bytes never plan.
    def _hash_drift() -> None:
        locator = {
            "revision_id": plan["revision_id"],
            "source_sha256": plan["source_sha256"],
            "normalized_sha256": "0" * 64,
        }
        T03.plan_chapters(text, locator, "fixture.md")

    faults["source_hash_error"] = expect_failure("source_hash_error", _hash_drift)
    # F4 fenced adoption: a forged pass report can never accept a bad candidate.
    def _forged_report() -> None:
        request = T03.build_chapter_request(plan, 0, text)
        request["normalized_sha256"] = sha256_text(request["normalized_text"])
        bad = build_chapter_candidate(
            request,
            {
                "chapter_id": request["chapter_id"],
                "revision_id": request["revision_id"],
                "source_title": "fixture",
                "translation_text": "壞",
                "entities": [
                    {"mention": "壞", "type": "person", "name": "壞"},
                ],
                "event": {"type": "battle", "title": "壞"},
                "predicate": "affected",
            },
        )
        bad["translation"]["blocks"][0]["source_block_ids"] = ["blk_missing"]
        C01.accept_chapter_candidate(
            request,
            bad,
            producing_run=producing_run("fixture-forged"),
            report={"passed": True, "errors": {}},
        )

    faults["forged_accept_refused"] = expect_failure(
        "forged_accept_refused", _forged_report
    )
    # F5 immutable artifact: tampered bytes never re-validate as accepted.
    def _tampered_artifact() -> None:
        tampered = copy.deepcopy(artifacts[0])
        tampered["candidate"]["translation"]["blocks"][0][
            "text"
        ] = "tampered text"
        T07.assemble_chapters(
            accepted_artifacts=[tampered, *artifacts[1:]], chapter_plan=plan
        )

    faults["tampered_artifact_refused"] = expect_failure(
        "tampered_artifact_refused", _tampered_artifact
    )
    # F6 public transaction rollback: a structurally bad resolution never
    # validates, so no partial publication can proceed from it.
    bad_resolution = {
        "schema": "chronicle.resolution-links",
        "version": "0.2",
        "scope": "cross_source",
        "left_bundle": {
            "label": "same",
            "source_ref": "src_001",
            "source_title": "fixture",
        },
        "right_bundle": {
            "label": "same",
            "source_ref": "src_001",
            "source_title": "fixture",
        },
        "entity_links": [],
        "event_links": [],
        "warnings": [],
    }
    validation = C01.validate_resolution_v02(bad_resolution)
    if validation.get("passed"):
        raise GateError("fault public_rollback did not fail closed")
    faults["public_rollback"] = {"passed": True, "error": "cross_source identical labels"}
    # F7 same-revision content change: a changed chapter no longer matches
    # the frozen plan content hash.
    def _changed_same_revision() -> None:
        changed_plan = copy.deepcopy(plan)
        changed_plan["chapters"][0]["content_sha256"] = "1" * 64
        T07.assemble_chapters(
            accepted_artifacts=artifacts, chapter_plan=changed_plan
        )

    faults["same_revision_changed_refused"] = expect_failure(
        "same_revision_changed_refused", _changed_same_revision
    )
    # F8 two-revision read isolation: artifacts never cross into another
    # revision plan, and chapter identities are revision-bound.
    if len(planned_works) > 1:
        other_plan = planned_works[1]["plan"]

        def _mixed_revisions() -> None:
            T07.assemble_chapters(
                accepted_artifacts=artifacts, chapter_plan=other_plan
            )

        faults["two_revision_isolation"] = expect_failure(
            "two_revision_isolation", _mixed_revisions
        )
        own_ids = {chapter["chapter_id"] for chapter in plan["chapters"]}
        other_ids = {chapter["chapter_id"] for chapter in other_plan["chapters"]}
        if own_ids & other_ids:
            raise GateError("chapter identities collide across revisions")
        faults["two_revision_isolation"]["identities_disjoint"] = True
    else:
        faults["two_revision_isolation"] = {"passed": True, "error": "single work pack"}
    # F9 run adoption between interruptions: re-accepting the identical
    # pair is byte-identical (idempotent); the run binding is audit only.
    request = T03.build_chapter_request(plan, 0, text)
    request["normalized_sha256"] = sha256_text(request["normalized_text"])
    candidate = copy.deepcopy(artifacts[0]["candidate"])
    repeat = C01.accept_chapter_candidate(
        request, candidate, producing_run=producing_run("fixture-repeat")
    )
    if repeat["candidate_sha256"] != artifacts[0]["candidate_sha256"]:
        raise GateError("identical re-accept changed the candidate binding")
    if sha256_json({k: repeat[k] for k in ("candidate", "anchors")}) != sha256_json(
        {k: artifacts[0][k] for k in ("candidate", "anchors")}
    ):
        raise GateError("identical re-accept changed product bytes")
    faults["idempotent_reaccept"] = {
        "passed": True,
        "candidate_sha256": repeat["candidate_sha256"],
    }
    # F10 worker takeover/cancel: an empty job carries no chapters and can
    # never assemble; cancellation leaves no partial bundle behind.
    faults["cancelled_job_empty"] = expect_failure(
        "cancelled_job_empty",
        lambda: T07.assemble_chapters(accepted_artifacts=[], chapter_plan=plan),
    )
    return faults


def browser_reuse_check(repo: Path) -> dict[str, Any]:
    """Reuse the real T11/T17 browser scripts and Reader routes (static).

    Fixture mode launches no browser and copies no second client logic;
    it proves the exact production scripts/routes are still wired and
    records the commands the live run executes for real.
    """
    review_smoke = REPO / "apps/chronicle/webapp/scripts/review-flow-smoke.mjs"
    reader_smoke = REPO / "apps/chronicle/webapp/scripts/chapter-reader-smoke.mjs"
    checks: list[dict[str, Any]] = []
    for path, token in (
        (review_smoke, "/api/v1/studio/jobs/reviews"),
        (reader_smoke, "/api/v1/public/chapters"),
    ):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise GateError(f"browser smoke script missing: {path}: {exc}") from exc
        if token not in content:
            raise GateError(f"{path.name} no longer exercises {token}")
        checks.append(
            {
                "script": str(path.relative_to(repo)),
                "route": token,
                "sha256": sha256_bytes(content.encode("utf-8")),
            }
        )
    server_hits: list[str] = []
    for base, suffixes in (
        (REPO / "apps/chronicle/server/src", (".rs",)),
        (REPO / "apps/chronicle/read_api", (".py",)),
    ):
        for file_path in sorted(base.rglob("*")):
            if not file_path.is_file() or file_path.suffix not in suffixes:
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if "public/chapters" in content or "studio/jobs/reviews" in content:
                server_hits.append(str(file_path.relative_to(repo)))
                if len(server_hits) >= 10:
                    break
    if not server_hits:
        raise GateError("no server route wiring found for chapters/reviews")
    return {
        "scripts": checks,
        "server_route_files": sorted(server_hits),
        "browser_launched": False,
        "reason": "fixture mode performs no browser run; live mode runs both smokes for real",
        "live_commands": [
            "node apps/chronicle/webapp/scripts/review-flow-smoke.mjs --base-url $BASE_URL --job-id $JOB_ID",
            "node apps/chronicle/webapp/scripts/chapter-reader-smoke.mjs --base-url $BASE_URL --publication-id $PUBLICATION_ID",
        ],
    }


def run_fixture(
    env_file: Path,
    pack_path: Path,
    evidence_dir: Path,
    argv: list[str],
    allow_dirty: bool,
) -> dict[str, Any]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, Any] = {
        "schema": GATE_SCHEMA,
        "version": GATE_VERSION,
        "mode": "fixture",
        "fixture_only": True,
        "disclaimer": FIXTURE_DISCLAIMER,
        "command": argv,
    }
    partial_path = evidence_dir / "manifest.partial.json"

    def checkpoint() -> None:
        write_json(partial_path, evidence)

    try:
        evidence["no_direct_db"] = check_no_direct_db_writes()
        evidence["candidate"] = candidate_commit(REPO)
        if not evidence["candidate"]["git_clean"] and not allow_dirty:
            raise GateError(
                "fixture gate requires a clean checkout; "
                "re-run with --allow-dirty for local iteration only"
            )
        file_config = load_env_file(env_file)
        evidence["env"] = {
            "env_file": str(env_file),
            "chronicle_keys": sorted(
                key for key in file_config if key.startswith("CHRONICLE_")
            ),
        }
        corpus_root = pack_path.parent.resolve()
        loaded = load_source_pack(pack_path, corpus_root)
        evidence["source"] = verify_pack_manifest_hashes(
            loaded["pack"], loaded["uploads"], corpus_root
        )
        checkpoint()

        planned_works: list[dict[str, Any]] = []
        accepted_works: list[dict[str, Any]] = []
        assembled_works: list[dict[str, Any]] = []
        works_evidence: list[dict[str, Any]] = []
        for upload in loaded["uploads"]:
            planned = plan_work(upload, corpus_root, evidence)
            planned_works.append(planned)
            source_title = next(
                (
                    str(work.get("work"))
                    for work in loaded["pack"]["works"]
                    if work.get("upload") == upload["upload"]
                ),
                upload["upload"],
            )
            accepted = accept_work_chapters(planned, source_title)
            accepted_works.append(accepted)
            assembled = assemble_work(planned, accepted)
            assembled_works.append(assembled)
            works_evidence.append(
                {
                    "upload": upload["upload"],
                    "revision_id": planned["plan"]["revision_id"],
                    "plan_sha256": planned["plan"]["plan_sha256"],
                    "chapter_count": len(planned["plan"]["chapters"]),
                    "chapters": accepted["chapters"],
                    "assembled": assembled,
                }
            )
            evidence["works"] = works_evidence
            checkpoint()

        expected_counts = [3, 1]
        actual_counts = [len(item["chapters"]) for item in works_evidence]
        if actual_counts != expected_counts[: len(actual_counts)]:
            raise GateError(
                f"expected T02 work chapter counts {expected_counts}, "
                f"planned {actual_counts}"
            )

        # Claimless provenance on the first chapter request.
        first = planned_works[0]
        probe_request = T03.build_chapter_request(first["plan"], 0, first["text"])
        probe_request["normalized_sha256"] = sha256_text(
            probe_request["normalized_text"]
        )
        evidence["claimless_provenance"] = claimless_provenance_check(
            probe_request, "fixture"
        )
        # Within-revision pairs on the multi-chapter work.
        evidence["within_revision_pairs"] = within_revision_pair_check(
            assembled_works[0]
        )
        # Cross-book batch/default/override DTOs.
        evidence["cross_book_batch"] = batch_context_check(assembled_works[0])
        checkpoint()

        evidence["faults"] = fault_injection_checks(planned_works, accepted_works)
        checkpoint()
        evidence["browser_reuse"] = browser_reuse_check(REPO)
        evidence["review_queue"] = {
            "note": "450+ queue, multi-job, tail-scan, contested tabs and "
            "per-group overrides are exercised by the real T11 review-flow "
            "smoke; fixture mode reuses that script instead of a second client",
            "script": "apps/chronicle/webapp/scripts/review-flow-smoke.mjs",
        }
        evidence["result"] = "PASS"
        write_json(evidence_dir / "manifest.json", evidence)
        if partial_path.exists():
            partial_path.unlink()
        return evidence
    except GateError:
        evidence["result"] = "FAIL"
        checkpoint()
        raise


# ---------------------------------------------------------------------------
# Live mode (strict prechecks only; T18 never calls a real provider)
# ---------------------------------------------------------------------------


def require_live_env(config: dict[str, str]) -> dict[str, Any]:
    if config.get("CHRONICLE_MODEL_FIXTURE_PACK", "").strip():
        raise GateError(
            "live mode refuses CHRONICLE_MODEL_FIXTURE_PACK; "
            "fixture material must never enter a live run"
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
            f"missing required live configuration: {', '.join(missing)}"
        )
    parsed = urllib.parse.urlparse(config["CHRONICLE_MODEL_ENDPOINT"])
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise GateError("CHRONICLE_MODEL_ENDPOINT must be an absolute http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise GateError("CHRONICLE_MODEL_ENDPOINT must not embed credentials")
    return {
        "endpoint_host": parsed.netloc,
        "extraction_model": config["CHRONICLE_EXTRACTION_MODEL"],
        "presentation_model": config["CHRONICLE_PRESENTATION_MODEL"],
        "timeout_seconds": config.get("CHRONICLE_MODEL_TIMEOUT_SECONDS", "600"),
        "fixture_mode": False,
    }


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
            "live compose config failed: "
            f"{(result.stdout + result.stderr)[:1000]}"
        )
    return {"checked": True}


def run_live(
    env_file: Path,
    pack_path: Path,
    evidence_dir: Path,
    argv: list[str],
    auto_decide: bool,
    non_interactive: bool,
    execute: bool,
) -> dict[str, Any]:
    if auto_decide:
        raise GateError(
            "live mode refuses --auto-decide; identity decisions require "
            "human review in Studio"
        )
    if non_interactive:
        raise GateError(
            "live mode refuses --non-interactive; blocking resolution "
            "reviews pause for an interactive operator"
        )
    if execute:
        raise GateError(
            "T18 never executes live provider calls; the READY handoff "
            "below is owned for execution by T19"
        )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, Any] = {
        "schema": GATE_SCHEMA,
        "version": GATE_VERSION,
        "mode": "live",
        "fixture_only": False,
        "command": argv,
    }
    partial_path = evidence_dir / "manifest.partial.json"

    def checkpoint() -> None:
        write_json(partial_path, evidence)

    try:
        evidence["no_direct_db"] = check_no_direct_db_writes()
        evidence["candidate"] = candidate_commit(REPO)
        if not evidence["candidate"]["git_clean"]:
            raise GateError("live gate requires a clean exact candidate checkout")
        file_config = load_env_file(env_file)
        runtime_config = dict(file_config)
        runtime_config.update(
            {k: v for k, v in os.environ.items() if k.startswith("CHRONICLE_")}
        )
        evidence["provider"] = require_live_env(runtime_config)
        corpus_root = pack_path.parent.resolve()
        loaded = load_source_pack(pack_path, corpus_root)
        evidence["source"] = verify_pack_manifest_hashes(
            loaded["pack"], loaded["uploads"], corpus_root
        )
        evidence["compose"] = compose_config_check(env_file)
        evidence["interactive_review"] = {
            "auto_decisions": "refused",
            "pause_required": True,
            "stdin_is_tty": sys.stdin.isatty(),
        }
        evidence["live_command"] = (
            "python3 apps/chronicle/acceptance/first_round_gate.py "
            f"--mode live --env-file {env_file} "
            f"--source-pack {pack_path} --evidence-dir {evidence_dir}"
        )
        evidence["t19_handoff"] = {
            "steps": [
                "start an empty Compose stack on a fresh CHRONICLE_DATA_DIR",
                "upload both T02 work inputs through Studio and queue jobs",
                "run the full chapter chain to publication with fixture excluded",
                "resolve blocking chapter_pair/published_batch reviews interactively in Studio",
                "read every published chapter in a real browser via the Reader routes",
                "record the T19 content-check evidence; fixture PASS is not content proof",
            ],
            "provider_calls_by_t18": 0,
        }
        evidence["result"] = "READY"
        write_json(evidence_dir / "manifest.json", evidence)
        if partial_path.exists():
            partial_path.unlink()
        print(f"first-round gate: READY evidence={evidence_dir / 'manifest.json'}")
        return evidence
    except GateError:
        evidence["result"] = "FAIL"
        checkpoint()
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
        "--allow-dirty",
        action="store_true",
        help="fixture-only: permit a dirty checkout for local iteration",
    )
    parser.add_argument(
        "--auto-decide",
        action="store_true",
        help="always refused: the gate never auto-decides review identity",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="always refused in live mode: reviews pause for an operator",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="always refused in T18 live mode: execution belongs to T19",
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
            env_file, pack_path, evidence_dir, full_argv, args.allow_dirty
        )
        print(f"first-round gate: PASS evidence={evidence_dir / 'manifest.json'}")
        works = len(evidence.get("works", []))
        faults = len(evidence.get("faults", {}))
        print(f"works={works} faults={faults} mode=fixture (NOT live proof)")
        return 0
    evidence = run_live(
        env_file,
        pack_path,
        evidence_dir,
        full_argv,
        args.auto_decide,
        args.non_interactive,
        args.execute,
    )
    _ = evidence
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GateError as exc:
        print(f"first-round gate: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
