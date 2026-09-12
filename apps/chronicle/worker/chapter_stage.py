"""Chronicle C2-R1-T13 thin chapter orchestration (worker wiring owner).

This module is the only place that wires the independently verified
chapter contracts into the real durable import chain:

- T03 ``chapter_plan`` / ``chapter_contract`` — natural-chapter planning
  and program-owned per-chapter requests;
- T05 ``chapter_extraction`` — one whole-chapter joint call plus at most
  one whole-chapter correction (never the old independent 2000-char
  chunk prompt);
- T06 ``model_provider`` / ``fixture_model`` — the real chapter provider
  selected through the formal production entry;
- T07 ``assembly.assemble_chapters`` — one revision bundle over all
  expected accepted chapters;
- T08 ``resolve_publish`` chapter initials plus the frozen mixed review
  plan (``chapter_pair`` + ``published_batch``);
- T04 ``chapter_store`` — lease-fenced accepted-chapter writes and the
  immutable publication rows reused by the atomic publish transaction.

Design rules (chapter-production.md sections 3/5-7):

- Eight stages and the jobs/chunks/runs authority are unchanged: every
  natural chapter is exactly one work chunk; no second chapter queue or
  run authority is introduced.
- Model waits never hold a database transaction. The lease is renewed
  before each chapter model call and every durable write re-verifies the
  current lease, so a slow model can neither block Studio cancellation
  nor hide a takeover.
- Accepting re-validates the exact request/candidate pair (T04) and the
  stored producing-run fingerprint. A run that already committed while
  its checkpoint commit never landed is adopted from its complete
  stored request/response with zero additional successful model calls.
- ``present`` only verifies already-published artifacts; it never
  re-translates a chapter and never substitutes a person/event blurb
  for the complete translation.
"""

from __future__ import annotations

import hashlib
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

_HERE = Path(__file__).resolve().parent
_PERSISTENCE_DIR = _HERE.parent / "persistence"
for _path in (str(_HERE), str(_PERSISTENCE_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import control_plane  # noqa: E402
from common import (  # noqa: E402
    PersistenceConflict,
    PersistenceError,
    sha256_json,
)

import assembly as chapter_assembly  # noqa: E402
import chapter_contract as chapter_contract  # noqa: E402
import chapter_extraction as chapter_extraction  # noqa: E402
import chapter_plan as chapter_plan  # noqa: E402
import chapter_prompt as chapter_prompt  # noqa: E402
import chapter_store as chapter_store  # noqa: E402
import reading_contract as reading_contract  # noqa: E402
import resolution_store as resolution_store  # noqa: E402
import resolve_publish as resolve_publish  # noqa: E402
import staged_store as staged_store  # noqa: E402

try:
    import psycopg  # noqa: E402
except ImportError as exc:  # pragma: no cover - deployment always vendors psycopg
    raise PersistenceError(
        "the Chronicle chapter stage requires psycopg "
        "(apps/chronicle/persistence/requirements.txt)"
    ) from exc

#: Version marker recorded on chapter stage checkpoints for audit.
CHAPTER_STAGE_VERSION = "c2r1t13-v1"

#: Control-plane output type for the frozen chapter review plan. Kept
#: distinct from the legacy C1 resolution outputs so recovery reuses the
#: exact frozen plan instead of rebuilding one.
CHAPTER_PLAN_OUTPUT_TYPE = "chapter-review-plan"

#: Explicit test-injection entry: a chapter fixture pack path. Production
#: never sets this; without it (and without a live chapter model) the
#: chapter path fails closed instead of faking success.
CHAPTER_FIXTURE_PACK_ENV = "CHRONICLE_CHAPTER_FIXTURE_PACK"

#: Formal production entry for the live joint chapter model.
CHAPTER_MODEL_ENV = "CHRONICLE_CHAPTER_MODEL"
CHAPTER_ENDPOINT_ENV = "CHRONICLE_MODEL_ENDPOINT"
CHAPTER_API_KEY_ENV = "CHRONICLE_MODEL_API_KEY"


# ---------------------------------------------------------------------------
# Production entry: chapter schema / provider / limits selection
# ---------------------------------------------------------------------------


def chapter_model_from_env(
    env: dict[str, str] | os._Environ[str] | None = None,
) -> Any | None:
    """Select the joint chapter model provider, or None when unconfigured.

    ``CHRONICLE_CHAPTER_FIXTURE_PACK`` is the explicit test-injection
    entry (a development chapter fixture pack path). Otherwise
    ``CHRONICLE_CHAPTER_MODEL`` plus ``CHRONICLE_MODEL_ENDPOINT``
    selects the live provider through the T06 chapter envelope.
    Anything else fails closed; the old fake executor is never an
    implicit fallback for new chapters.
    """
    source = os.environ if env is None else env
    fixture_pack = (source.get(CHAPTER_FIXTURE_PACK_ENV) or "").strip()
    chapter_name = (source.get(CHAPTER_MODEL_ENV) or "").strip()
    if fixture_pack:
        if chapter_name or (source.get(CHAPTER_ENDPOINT_ENV) or "").strip():
            raise PersistenceError(
                f"{CHAPTER_FIXTURE_PACK_ENV} cannot be combined with live "
                "chapter model configuration"
            )
        import fixture_model as fixture_model  # noqa: E402

        return fixture_model.models_from_chapter_fixture_pack(fixture_pack)
    if not chapter_name:
        return None
    endpoint = (source.get(CHAPTER_ENDPOINT_ENV) or "").strip()
    if not endpoint:
        raise PersistenceError(
            f"{CHAPTER_ENDPOINT_ENV} is required when {CHAPTER_MODEL_ENV} "
            "is configured"
        )
    import model_provider as model_provider  # noqa: E402

    limits = chapter_limits_from_env(source)
    return model_provider.build_chapter_model(
        chapter_name,
        endpoint,
        api_key=(source.get(CHAPTER_API_KEY_ENV) or "").strip() or None,
        timeout_seconds=model_provider.timeout_from_env(source),
        max_response_bytes=limits.max_response_bytes,
        max_output_tokens=limits.max_output_tokens,
        candidate_version=candidate_version_for_model(SimpleNamespace(name=chapter_name)),
    )


def chapter_limits_from_env(
    env: dict[str, str] | os._Environ[str] | None = None,
) -> chapter_contract.ChapterLimits:
    """Return the fixed chapter engineering envelope (T01 ChapterLimits)."""
    if env is None:
        return chapter_contract.ChapterLimits.from_env()
    return chapter_contract.ChapterLimits.from_env(dict(env))


def require_production_entry(
    *,
    source_dir: Any | None,
    extraction_model: Any | None,
    chapter_model: Any | None,
) -> None:
    """Enforce the production entry's explicit model rule (fail closed).

    A production worker pointed at a real source directory must have
    an explicit extraction capability — either the joint chapter
    model or a chunk extraction model. Without either, the entry
    refuses to start instead of falling through to legacy/fake
    branching. This is the production-entry rule; the library runner
    stays composable for explicit test injection (pinned C1
    segmentation/extraction tests rely on that).
    """
    if source_dir is not None and extraction_model is None and chapter_model is None:
        raise PersistenceError(
            "a production worker with --source-dir/CHRONICLE_SOURCE_DIR "
            "requires an explicit model (CHRONICLE_CHAPTER_MODEL for the "
            "joint chapter pipeline or CHRONICLE_EXTRACTION_MODEL for "
            "chunk extraction); refusing to start without one"
        )


#: Candidate generation bound to each model family. The live production
#: provider emits 0.3 person-state annotations on top of the reading
#: annotations; the frozen first-round development fixture emits 0.1 and the
#: second-round reading fixture emits 0.2.
CANDIDATE_VERSIONS = (
    chapter_contract.CANDIDATE_VERSION,
    reading_contract.CANDIDATE_VERSION,
    chapter_contract.PRODUCTION_CANDIDATE_VERSION,
)


def candidate_version_for_model(model: Any) -> str:
    """Return the chapter-candidate generation a model produces.

    An explicit ``candidate_version`` on the provider wins. Otherwise a
    development fixture is recognized by its ``fixture:<version>:<kind>``
    name (``reading-chapter`` is 0.2, ``person-state-chapter`` is 0.3); every
    other provider is the live joint model, whose production default is the
    0.3 person-state contract. This is the only place the worker decides
    which candidate version a planned request must declare, so the request,
    prompt, model strict format and acceptance validator always agree.
    """
    if model is None:
        return chapter_contract.PRODUCTION_CANDIDATE_VERSION
    declared = getattr(model, "candidate_version", None)
    if declared is not None:
        if declared not in CANDIDATE_VERSIONS:
            raise PersistenceError(
                f"chapter model declares unsupported candidate version {declared!r}"
            )
        return str(declared)
    import fixture_model as fixture_model  # noqa: E402

    name = str(getattr(model, "name", ""))
    if name.endswith(":" + fixture_model.PERSON_STATE_CHAPTER_MODEL_SUFFIX):
        return chapter_contract.PRODUCTION_CANDIDATE_VERSION
    if name.endswith(":" + fixture_model.READING_CHAPTER_MODEL_SUFFIX):
        return reading_contract.CANDIDATE_VERSION
    if name.endswith(":" + fixture_model.CHAPTER_MODEL_SUFFIX):
        return chapter_contract.CANDIDATE_VERSION
    return chapter_contract.PRODUCTION_CANDIDATE_VERSION


# ---------------------------------------------------------------------------
# Planning: revision binding, plan, and program-owned requests
# ---------------------------------------------------------------------------


def read_revision_binding(
    conn, *, job_id: uuid.UUID
) -> dict[str, Any]:
    """Read the immutable revision binding for a job (one committed read)."""
    row = conn.execute(
        """
        SELECT j.revision_id, r.source_sha256, r.filename, r.document_id
        FROM chronicle.ingestion_jobs j
        JOIN chronicle.document_revisions r ON r.revision_id = j.revision_id
        WHERE j.job_id = %s
        """,
        (job_id,),
    ).fetchone()
    if row is None:
        raise PersistenceError(f"unknown job {job_id}")
    filename = row[2] or "upload.txt"
    if not isinstance(filename, str) or not filename:
        raise PersistenceError(f"job {job_id} revision carries no filename")
    return {
        "revision_id": row[0],
        "source_sha256": row[1],
        "filename": filename,
        "document_id": row[3],
    }


def plan_job_chapters(
    *,
    text: str,
    source_sha256: str,
    binding: dict[str, Any],
    limits: chapter_contract.ChapterLimits,
    candidate_version: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Plan natural chapters and build one program-owned request per chapter.

    Pure compute (no database, no model): the T03 plan plus one T01
    request per chapter in plan order. Hash drift between the supplied
    text and the immutable revision binding fails closed.

    ``candidate_version`` selects the joint candidate generation the
    requests declare (0.1 first round, 0.2 reading, 0.3 person states); it defaults
    to the frozen 0.1 generation so existing callers are unchanged, while the
    worker passes the model's version through
    :func:`candidate_version_for_model` so a live run plans production 0.3. The
    request's declared version is the single signal the prompt renderer, the
    model strict format and the acceptance validator all read, so a run
    cannot mix the registered candidate contracts.

    The T01 identity check requires ``normalized_sha256`` to hash to
    the request's chapter ``normalized_text``; the T03 builder carries
    the revision-level hash there instead. This wiring layer rebinds
    each request to its chapter slice hash and cross-checks it against
    the plan chapter's ``content_sha256`` (fail closed on any drift),
    without changing the T03 helper itself. ``revision_id`` /
    ``source_sha256`` / ``chapter_id`` keep the revision-level binding.
    """
    version = candidate_version or chapter_contract.CANDIDATE_VERSION
    if version not in CANDIDATE_VERSIONS:
        raise PersistenceError(
            f"chapter candidate version must be one of {list(CANDIDATE_VERSIONS)}, "
            f"got {version!r}"
        )
    normalized_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    locator = {
        "revision_id": str(binding["revision_id"]),
        "source_sha256": source_sha256,
        "normalized_sha256": normalized_sha256,
    }
    if binding.get("document_id") is not None:
        locator["document_id"] = str(binding["document_id"])
    plan = chapter_plan.plan_chapters(
        text, locator, binding["filename"], limits=limits
    )
    content_by_id = {
        str(chapter["chapter_id"]): chapter.get("content_sha256")
        for chapter in plan.get("chapters") or []
    }
    requests = []
    for index in range(plan["chapter_count"]):
        request = chapter_plan.build_chapter_request(
            plan, index, text, limits=limits
        )
        slice_sha256 = hashlib.sha256(
            request["normalized_text"].encode("utf-8")
        ).hexdigest()
        expected = content_by_id.get(str(request["chapter_id"]))
        if not isinstance(expected, str) or slice_sha256 != expected:
            raise PersistenceError(
                f"chapter {index} slice hash does not match the planned "
                "chapter content hash; refusing to extract bytes outside "
                "the plan"
            )
        request["normalized_sha256"] = slice_sha256
        # Bind the exact candidate generation this execution must produce.
        request["schema_versions"] = {
            "candidate": version,
            "bundle": "0.1",
        }
        requests.append(request)
    return plan, requests


def chapter_index_by_id(plan: dict[str, Any]) -> dict[str, int]:
    """Return the assembly plan chapter order required by T08 candidacy."""
    mapping: dict[str, int] = {}
    for chapter in plan.get("chapters") or []:
        mapping[str(chapter["chapter_id"])] = int(chapter["chapter_index"])
    if not mapping:
        raise PersistenceError("chapter plan carries no chapters")
    return mapping


# ---------------------------------------------------------------------------
# Chapter chunk topology: exactly one work chunk per natural chapter
# ---------------------------------------------------------------------------


def ensure_chapter_topology(
    conn, *, job_id: uuid.UUID, worker: str, plan: dict[str, Any], text: str
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Ensure one section plus one chunk per planned chapter (idempotent).

    Reuses existing ``(job, index)`` rows on re-entry after a crash, so
    resume never duplicates chunks or loses their checkpoints. Chunk
    ranges are the chapter's absolute normalized coordinates; the
    content hash binds the exact chapter bytes.
    """
    chapters = plan.get("chapters") or []
    if not chapters:
        raise PersistenceError("chapter plan carries no chapters")
    with conn.transaction():
        control_plane.require_job_lease(conn, job_id=job_id, worker=worker)
        row = conn.execute(
            """
            SELECT section_id FROM chronicle.ingestion_sections
            WHERE job_id = %s AND section_index = 0
            """,
            (job_id,),
        ).fetchone()
        if row is not None:
            section_id = row[0]
        else:
            try:
                with conn.transaction(savepoint_name="chapter_section_insert"):
                    section_id = control_plane.create_section(
                        conn, job_id=job_id, section_index=0,
                        label="chapters", source_start=0,
                        source_end=len(text), kind="document",
                    )
            except PersistenceConflict:
                section_id = None
        if section_id is None:
            row = conn.execute(
                """
                SELECT section_id FROM chronicle.ingestion_sections
                WHERE job_id = %s AND section_index = 0
                """,
                (job_id,),
            ).fetchone()
            if row is None:  # pragma: no cover - conflict implies a row
                raise PersistenceError(
                    f"chapter section vanished for job {job_id}"
                )
            section_id = row[0]
    chunk_ids: list[uuid.UUID] = []
    source_sha256 = plan["source_sha256"]
    for chapter in chapters:
        index = int(chapter["chapter_index"])
        content_sha256 = hashlib.sha256(
            text[chapter["start"]:chapter["end"]].encode("utf-8")
        ).hexdigest()
        with conn.transaction():
            control_plane.require_job_lease(conn, job_id=job_id, worker=worker)
            row = conn.execute(
                """
                SELECT chunk_id, source_start, source_end
                FROM chronicle.ingestion_chunks
                WHERE job_id = %s AND chunk_index = %s
                """,
                (job_id, index),
            ).fetchone()
            if row is not None:
                if int(row[1]) != int(chapter["start"]) or int(row[2]) != int(
                    chapter["end"]
                ):
                    raise PersistenceError(
                        f"job {job_id} chapter chunk {index} range "
                        f"[{row[1]},{row[2]}) does not match planned chapter "
                        f"[{chapter['start']},{chapter['end']}); refusing to "
                        "extract on a stale chunk set"
                    )
                chunk_ids.append(row[0])
                continue
            try:
                chunk_ids.append(
                    control_plane.record_chunk(
                        conn, job_id=job_id, section_id=section_id,
                        chunk_index=index,
                        source_start=int(chapter["start"]),
                        source_end=int(chapter["end"]),
                        source_sha256=source_sha256,
                        content_sha256=content_sha256,
                    )
                )
            except PersistenceConflict:
                row = conn.execute(
                    """
                    SELECT chunk_id FROM chronicle.ingestion_chunks
                    WHERE job_id = %s AND chunk_index = %s
                    """,
                    (job_id, index),
                ).fetchone()
                if row is None:  # pragma: no cover - conflict implies a row
                    raise PersistenceError(
                        f"chapter chunk {index} vanished for job {job_id}"
                    )
                chunk_ids.append(row[0])
    # Fail closed on a stale chunk set left by any other topology.
    with conn.transaction():
        count = conn.execute(
            "SELECT count(*) FROM chronicle.ingestion_chunks WHERE job_id = %s",
            (job_id,),
        ).fetchone()[0]
    if int(count) != len(chapters):
        raise PersistenceError(
            f"job {job_id} persists {count} chunks but the chapter plan "
            f"needs {len(chapters)}; refusing to extract on a stale chunk set"
        )
    return section_id, chunk_ids


# ---------------------------------------------------------------------------
# Extract: whole-chapter joint calls with lease renewal and adoption
# ---------------------------------------------------------------------------


def _heartbeat(database_url: str, *, job_id: uuid.UUID, worker: str,
               lease_seconds: int) -> None:
    """Renew the lease in one committed transaction (LeaseLost on takeover)."""
    with psycopg.connect(database_url) as conn:
        control_plane.heartbeat_job_strict(
            conn, job_id=job_id, worker=worker, lease_seconds=lease_seconds
        )


def _producing_run_for(run_id: uuid.UUID, model_name: str) -> dict[str, Any]:
    """Build the T01 producing-run binding for one persisted chunk run."""
    if not isinstance(model_name, str) or not model_name:
        raise PersistenceError("chapter producing run requires the model name")
    return {
        "run_id": str(run_id),
        "model": model_name,
        "prompt_schema_version": chapter_prompt.PROMPT_VERSION,
    }


def _chapter_error_message(result: dict[str, Any]) -> str:
    """Derive the persisted/logged message for a failed chapter result.

    The run checkpoint carries no "error" key, so the message must be
    derived here and shared by the persisted run row and the
    chapter_failed log event (reading it back from the checkpoint
    always yields None).
    """
    if not isinstance(result, dict):
        return "chapter extraction failed closed"
    error = result.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message
    if isinstance(error, str) and error.strip():
        return error
    return "chapter extraction failed closed"


def _read_runs(conn, chunk_id: uuid.UUID) -> list[tuple[int, str, dict[str, Any]]]:
    rows = conn.execute(
        """
        SELECT attempt, status, checkpoint
        FROM chronicle.ingestion_chunk_runs
        WHERE chunk_id = %s ORDER BY attempt
        """,
        (chunk_id,),
    ).fetchall()
    return [
        (int(attempt), str(status), checkpoint if isinstance(checkpoint, dict) else {})
        for attempt, status, checkpoint in rows
    ]


def _newest_accepted_run(
    runs: list[tuple[int, str, dict[str, Any]]],
) -> tuple[int, dict[str, Any], dict[str, Any]] | None:
    """Return the newest completed run carrying an accepted candidate."""
    for attempt, status, checkpoint in reversed(runs):
        if status != "completed" or checkpoint.get("accepted") is not True:
            continue
        candidate = checkpoint.get("candidate")
        request = checkpoint.get("request")
        if isinstance(candidate, dict) and isinstance(request, dict):
            return attempt, request, candidate
    return None


def _adopt_accepted_run(
    database_url: str,
    *,
    job_id: uuid.UUID,
    chunk_id: uuid.UUID,
    worker: str,
    request: dict[str, Any],
    lease_seconds: int,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> bool:
    """Adopt an already-committed accepted run with zero new model calls.

    Closes the crash window between the accepted run commit and the
    accepted-layer/status commit: the complete stored request/response
    is re-verified (fingerprint, chapter, revision, and full T01
    validation) before the T04 accept entry runs. Anything drifted
    fails closed instead of being adopted.
    """
    with psycopg.connect(database_url) as conn:
        runs = _read_runs(conn, chunk_id)
    adopted = _newest_accepted_run(runs)
    if adopted is None:
        return False
    run_attempt, stored_request, candidate = adopted
    expected_fp = chapter_contract.request_fingerprint(request)
    stored_fp = stored_request.get("request_fingerprint") or chapter_contract.request_fingerprint(
        stored_request
    )
    if stored_fp != expected_fp:
        raise PersistenceError(
            f"chapter chunk {chunk_id} stored run {run_attempt} fingerprint "
            "does not match the current chapter request; refusing to adopt "
            "a run for different bytes/config"
        )
    if stored_request.get("chapter_id") != request.get("chapter_id") or stored_request.get(
        "revision_id"
    ) != request.get("revision_id"):
        raise PersistenceError(
            f"chapter chunk {chunk_id} stored run {run_attempt} binds a "
            "different chapter/revision; refusing adoption"
        )
    report = chapter_contract.validate_chapter_candidate(request, candidate)
    if not report.get("passed"):
        raise PersistenceError(
            f"chapter chunk {chunk_id} stored run {run_attempt} candidate "
            "no longer validates; refusing adoption"
        )
    with psycopg.connect(database_url) as conn:
        control_plane.set_chunk_status_fenced(
            conn, job_id=job_id, chunk_id=chunk_id,
            status="running", worker=worker,
        )
    with psycopg.connect(database_url) as conn:
        run_id = conn.execute(
            """
            SELECT run_id FROM chronicle.ingestion_chunk_runs
            WHERE chunk_id = %s AND attempt = %s
            """,
            (chunk_id, run_attempt),
        ).fetchone()
        if run_id is None:  # pragma: no cover - row was just read
            raise PersistenceError(f"chapter chunk {chunk_id} run vanished")
        stored_model = None
        model_row = conn.execute(
            """
            SELECT checkpoint FROM chronicle.ingestion_chunk_runs
            WHERE chunk_id = %s AND attempt = %s
            """,
            (chunk_id, run_attempt),
        ).fetchone()
        if model_row is not None and isinstance(model_row[0], dict):
            stored_model = model_row[0].get("model")
        chapter_store.record_accepted_chapter_fenced(
            conn, job_id=job_id, chunk_id=chunk_id, worker=worker,
            request=request, candidate=candidate,
            producing_run=_producing_run_for(run_id[0], stored_model),
        )
        conn.commit()
    if on_event is not None:
        on_event(
            "chapter_run_adopted",
            {"chunk_id": str(chunk_id), "run_attempt": run_attempt},
        )
    return True


def _failed_outcome(database_url: str, chunk_id: uuid.UUID) -> str:
    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            SELECT attempt, max_attempts
            FROM chronicle.ingestion_chunks WHERE chunk_id = %s
            """,
            (chunk_id,),
        ).fetchone()
    if row is None:  # pragma: no cover - defensive
        raise PersistenceError(f"unknown chunk {chunk_id}")
    if int(row[0]) >= int(row[1]):
        return "needs_review"
    return "failed"


def execute_chapter_extract(
    database_url: str,
    *,
    job_id: uuid.UUID,
    worker: str,
    plan: dict[str, Any],
    requests: list[dict[str, Any]],
    model: Any,
    limits: chapter_contract.ChapterLimits,
    lease_seconds: int,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    halt: Callable[[uuid.UUID], str | None] | None = None,
) -> str:
    """Execute one whole-chapter joint call per planned chapter.

    Returns 'ok'/'failed'/'needs_review' or a caller halt
    ('cancelled'/'stopped'). Raises :class:`LeaseLost` when this worker
    no longer holds the lease. No database transaction is ever held
    across a model call; the lease is renewed before every call and
    every durable write is lease-fenced. Completed chapters are never
    re-run; a committed-but-uncheckpointed accepted run is adopted with
    zero new model calls after full request/response re-verification.
    """
    if model is None or not callable(getattr(model, "complete", None)):
        raise PersistenceError(
            "chapter extraction requires a joint chapter model with "
            "complete(prompt)->str; refusing to fake success"
        )
    model_name = getattr(model, "name", None)
    if not isinstance(model_name, str) or not model_name:
        raise PersistenceError("chapter model must carry a non-empty string name")
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            """
            SELECT chunk_id, chunk_index, status
            FROM chronicle.ingestion_chunks
            WHERE job_id = %s ORDER BY chunk_index
            """,
            (job_id,),
        ).fetchall()
    if [int(row[1]) for row in rows] != list(range(plan["chapter_count"])):
        raise PersistenceError(
            f"job {job_id} chapter chunks do not match the planned "
            f"{plan['chapter_count']} chapters; refusing to extract on a "
            "stale chunk set (run the segment stage first)"
        )
    for chunk_id, chunk_index, status in rows:
        if halt is not None:
            outcome = halt(job_id)
            if outcome is not None:
                return outcome
        request = requests[int(chunk_index)]
        if status == "completed":
            continue  # checkpoint skip: never re-run succeeded work
        if status not in ("pending", "running", "failed", "needs_review"):
            raise PersistenceError(
                f"chunk {chunk_id} has unexpected status {status!r}"
            )
        # Crash-window reconciliation first: adopt with zero model calls.
        if _adopt_accepted_run(
            database_url, job_id=job_id, chunk_id=chunk_id, worker=worker,
            request=request, lease_seconds=lease_seconds, on_event=on_event,
        ):
            continue
        with psycopg.connect(database_url) as conn:
            control_plane.set_chunk_status_fenced(
                conn, job_id=job_id, chunk_id=chunk_id,
                status="running", worker=worker,
            )
        # Renew the lease immediately before the model wait; no
        # transaction is open across the call below.
        _heartbeat(
            database_url, job_id=job_id, worker=worker,
            lease_seconds=lease_seconds,
        )
        result = chapter_extraction.extract_chapter(request, model, limits=limits)
        if halt is not None:
            outcome = halt(job_id)
            if outcome is not None:
                return outcome
        # Re-verify the lease after the model wait and before any
        # durable write: a takeover during the wait halts here with
        # LeaseLost instead of recording a run the new owner must
        # disambiguate.
        _heartbeat(
            database_url, job_id=job_id, worker=worker,
            lease_seconds=lease_seconds,
        )
        run_checkpoint = {
            "chapter_stage_version": CHAPTER_STAGE_VERSION,
            "accepted": bool(result.get("accepted")),
            "request": request,
            "request_fingerprint": result.get("request_fingerprint"),
            "fingerprints": result.get("fingerprints"),
            "attempts": result.get("attempts"),
            "correction_rounds_used": result.get("correction_rounds_used"),
            "model": model_name,
        }
        candidate = None
        if result.get("accepted"):
            artifact = result.get("artifact") or {}
            candidate = artifact.get("candidate")
            if not isinstance(candidate, dict):
                raise PersistenceError(
                    f"chapter chunk {chunk_id} accepted result carries no candidate"
                )
            run_checkpoint["candidate"] = candidate
        # The same message goes to the persisted run row and to the
        # chapter_failed log event: reading it back from run_checkpoint
        # always yields None because the checkpoint carries no "error" key.
        run_error = _chapter_error_message(result)
        with psycopg.connect(database_url) as conn:
            _, run_attempt = control_plane.record_chunk_run_fenced(
                conn, job_id=job_id, chunk_id=chunk_id,
                status="completed" if result.get("accepted") else "failed",
                worker=worker, checkpoint=run_checkpoint,
                error=None if result.get("accepted") else run_error,
            )
        if not result.get("accepted"):
            with psycopg.connect(database_url) as conn:
                control_plane.set_chunk_status_fenced(
                    conn, job_id=job_id, chunk_id=chunk_id,
                    status="failed", worker=worker,
                )
            if on_event is not None:
                on_event(
                    "chapter_failed",
                    {"chunk_id": str(chunk_id), "error": run_error},
                )
            return _failed_outcome(database_url, chunk_id)
        # Accept under the lease with the persisted run identity; the
        # T04 entry re-validates the exact pair before writing.
        with psycopg.connect(database_url) as conn:
            run_id = conn.execute(
                """
                SELECT run_id FROM chronicle.ingestion_chunk_runs
                WHERE chunk_id = %s AND attempt = %s
                """,
                (chunk_id, run_attempt),
            ).fetchone()
            if run_id is None:  # pragma: no cover - row was just written
                raise PersistenceError(f"chapter chunk {chunk_id} run vanished")
            chapter_store.record_accepted_chapter_fenced(
                conn, job_id=job_id, chunk_id=chunk_id, worker=worker,
                request=request, candidate=candidate,
                producing_run=_producing_run_for(run_id[0], model_name),
            )
            conn.commit()
        if on_event is not None:
            on_event("chapter_completed", {"chunk_id": str(chunk_id)})
    return "ok"


# ---------------------------------------------------------------------------
# Assemble / resolve / publish / present over accepted chapters
# ---------------------------------------------------------------------------


def execute_chapter_assemble(
    database_url: str,
    *,
    job_id: uuid.UUID,
    worker: str,
    plan: dict[str, Any],
    lease_seconds: int,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], str]:
    """Assemble every expected accepted chapter (fail closed on partials).

    Returns ``(assembled, bundle_sha256)`` and records the deterministic
    artifact as the job's ``assembled-source-bundle`` output. Pure
    compute happens with no connection open.
    """
    _heartbeat(
        database_url, job_id=job_id, worker=worker,
        lease_seconds=lease_seconds,
    )
    with psycopg.connect(database_url) as conn:
        accepted = chapter_store.read_accepted_chapters(conn, job_id=job_id)
        revision_id = conn.execute(
            "SELECT revision_id FROM chronicle.ingestion_jobs WHERE job_id = %s",
            (job_id,),
        ).fetchone()
    if revision_id is None:
        raise PersistenceError(f"unknown job {job_id}")
    revision_id = revision_id[0]
    # No connection is open across assembly: pure compute only.
    assembled = chapter_assembly.assemble_chapters(
        accepted_artifacts=[entry["artifact"] for entry in accepted],
        chapter_plan=plan,
    )
    bundle_sha256 = sha256_json(assembled["bundle"])
    report = assembled.get("report") if isinstance(assembled.get("report"), dict) else {}
    payload = {
        "bundle_sha256": bundle_sha256,
        "report": report,
        "bundle": assembled["bundle"],
        "chapter_by_ref": report.get("chapter_by_ref") or assembled.get("chapter_by_ref"),
    }
    # C2-R3-T08: a 0.3 assembled bundle persists its person-state evidence as
    # binding input for the resolve review plan and the publish compilation.
    # A 0.1/0.2 bundle carries no state and stays byte-compatible with the
    # earlier reading publish path.
    if isinstance(report.get("person_state"), dict):
        payload["person_states"] = assembled.get("person_states")
        payload["person_state_evidence"] = assembled.get("person_state_evidence")
    with psycopg.connect(database_url) as conn:
        control_plane.record_output_fenced(
            conn, job_id=job_id, revision_id=revision_id,
            worker=worker, artifact_type=chapter_assembly.ARTIFACT_TYPE,
            artifact_sha256=bundle_sha256,
            payload=payload,
        )
        control_plane.write_stage_checkpoint_fenced(
            conn, job_id=job_id, stage="assemble", worker=worker,
            checkpoint={
                "chapter_stage_version": CHAPTER_STAGE_VERSION,
                "assembly_version": chapter_assembly.CHAPTER_ASSEMBLY_VERSION,
                "artifact_sha256": bundle_sha256,
                "report": assembled["report"],
                "authoritative": False,
                "authority_note": chapter_assembly.NON_AUTHORITATIVE_NOTE,
            },
        )
        control_plane.advance_stage_fenced(
            conn, job_id=job_id, stage="assemble",
            status="completed", worker=worker,
        )
    if on_event is not None:
        on_event("stage_completed", {"stage": "assemble"})
    return assembled, bundle_sha256


def _read_assembled_bundle(
    database_url: str, job_id: uuid.UUID
) -> tuple[dict[str, Any], uuid.UUID, dict[str, str]]:
    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            SELECT o.payload, j.revision_id
            FROM chronicle.ingestion_outputs o
            JOIN chronicle.ingestion_jobs j ON j.job_id = o.job_id
            WHERE o.job_id = %s AND o.artifact_type = %s
            ORDER BY o.created_at DESC LIMIT 1
            """,
            (job_id, chapter_assembly.ARTIFACT_TYPE),
        ).fetchone()
    if row is None or not isinstance(row[0], dict):
        raise PersistenceError(
            f"job {job_id} has no assembled chapter bundle; refusing to "
            "resolve an unknown bundle"
        )
    payload = row[0]
    bundle = payload.get("bundle")
    if not isinstance(bundle, dict):
        raise PersistenceError(
            f"job {job_id} assembled output carries no source bundle"
        )
    mapping = payload.get("chapter_by_ref")
    if not isinstance(mapping, dict) or not mapping:
        report = payload.get("report")
        mapping = report.get("chapter_by_ref") if isinstance(report, dict) else None
    if not isinstance(mapping, dict) or not mapping:
        raise PersistenceError(
            f"job {job_id} assembled output carries no chapter_by_ref map"
        )
    return bundle, row[1], {str(key): str(value) for key, value in mapping.items()}


def read_assembled_state(
    database_url: str, job_id: uuid.UUID
) -> dict[str, Any] | None:
    """Return the frozen 0.3 person-state assembly from the assemble output.

    The assembled bundle row persists the T03 ``person_states`` block, its
    evidence manifests and the person-state report next to the source bundle
    so resolve freezes a review plan over exactly the accepted bytes and
    publish compiles from the same evidence instead of re-running anything.
    Returns ``None`` for a 0.1/0.2 assembled output that carries no state.
    """
    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            SELECT payload FROM chronicle.ingestion_outputs
            WHERE job_id = %s AND artifact_type = %s
            ORDER BY created_at DESC LIMIT 1
            """,
            (job_id, chapter_assembly.ARTIFACT_TYPE),
        ).fetchone()
    if row is None or not isinstance(row[0], dict):
        raise PersistenceError(
            f"job {job_id} has no assembled chapter bundle; refusing to "
            "read person-state evidence"
        )
    payload = row[0]
    person_states = payload.get("person_states")
    evidence = payload.get("person_state_evidence")
    if not isinstance(person_states, dict) or not isinstance(evidence, list):
        return None
    report = payload.get("report")
    person_report = report.get("person_state") if isinstance(report, dict) else None
    if not isinstance(person_report, dict):
        person_report = report if isinstance(report, dict) else {}
    return {
        "person_states": person_states,
        "evidence_manifests": evidence,
        "report": person_report,
    }


def _read_plan_output(
    database_url: str, job_id: uuid.UUID
) -> dict[str, Any] | None:
    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            SELECT payload FROM chronicle.ingestion_outputs
            WHERE job_id = %s AND artifact_type = %s
            ORDER BY created_at DESC LIMIT 1
            """,
            (job_id, CHAPTER_PLAN_OUTPUT_TYPE),
        ).fetchone()
    if row is None or not isinstance(row[0], dict):
        return None
    return row[0]


def _read_resolutions_by_sha(
    database_url: str, shas: list[str]
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url) as conn:
        fetched = conn.execute(
            """
            SELECT artifact_sha256, payload
            FROM chronicle.resolution_artifacts
            WHERE artifact_sha256 = ANY(%s)
            """,
            (sorted(set(shas)),),
        ).fetchall()
    by_sha = {row[0]: row[1] for row in fetched}
    initials: list[dict[str, Any]] = []
    for sha in shas:
        payload = by_sha.get(sha)
        if not isinstance(payload, dict):
            raise PersistenceError(
                f"frozen initial resolution {sha!r} is not persisted; "
                "refusing to resolve from missing evidence"
            )
        initials.append(payload)
    return initials


def _settle_person_state_resolve(
    database_url: str,
    *,
    job_id: uuid.UUID,
    worker: str,
    revision_id: uuid.UUID,
    final: list[dict[str, Any]],
    base_catalog_sha256: str,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> str:
    """Freeze/adopt the 0.3 state-evidence reviews after identity resolution.

    The identity Resolution reviews finish first; then one frozen
    ``chapter_state_evidence`` package per chapter is opened (or adopted on
    resume) and the job keeps parking in ``needs_review`` until every package
    is terminal. The immutable assessment artifact is persisted by the unique
    publish transaction, not here, so a takeover never half-collects state.
    Returns ``"needs_review"`` while packages are open and ``"ok"`` otherwise
    (including a non-0.3 job with no state evidence).
    """
    assembly = read_assembled_state(database_url, job_id)
    if assembly is None:
        return "ok"
    with psycopg.connect(database_url) as conn:
        accepted = chapter_store.read_accepted_chapters(conn, job_id=job_id)
    plan = resolve_publish.build_person_state_plan(
        job_id=job_id, revision_id=revision_id,
        accepted_artifacts=[entry["artifact"] for entry in accepted],
        assembly=assembly, final_resolutions=final,
        base_catalog_sha256=base_catalog_sha256,
    )
    with psycopg.connect(database_url) as conn:
        control_plane.record_output_fenced(
            conn, job_id=job_id, revision_id=revision_id, worker=worker,
            artifact_type=resolve_publish.PERSON_STATE_PLAN_OUTPUT_TYPE,
            artifact_sha256=sha256_json(plan),
            payload={"plan": plan, "plan_fingerprint": plan["plan_fingerprint"]},
        )
        conn.commit()
    with psycopg.connect(database_url) as conn:
        resolve_publish.person_state_review.open_person_state_reviews(
            conn, job_id=job_id, plan=plan
        )
        conn.commit()
    with psycopg.connect(database_url) as conn:
        open_count = resolve_publish.open_person_state_review_count(
            conn, job_id=job_id
        )
    if open_count > 0:
        with psycopg.connect(database_url) as conn:
            control_plane.write_stage_checkpoint_fenced(
                conn, job_id=job_id, stage="resolve", worker=worker,
                checkpoint={
                    "chapter_stage_version": CHAPTER_STAGE_VERSION,
                    "person_state_plan_fingerprint": plan["plan_fingerprint"],
                    "person_state_open_reviews": open_count,
                    "authoritative": False,
                },
            )
        if on_event is not None:
            on_event(
                "stage_needs_review",
                {"stage": "resolve", "person_state_open_reviews": open_count},
            )
        return "needs_review"
    return "ok"


def _settle_resolve(
    database_url: str,
    *,
    job_id: uuid.UUID,
    worker: str,
    revision_id: uuid.UUID,
    frozen_plan: dict[str, Any],
    initials: list[dict[str, Any]],
    assembled_sha: str,
    base_catalog_sha256: str,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> str:
    """Adopt-or-open the frozen reviews, then park or finalize (no rebuild)."""
    with psycopg.connect(database_url) as conn:
        resolve_publish.open_chapter_reviews(
            conn, job_id=job_id, plan=frozen_plan,
            initial_resolutions=initials, revision_id=revision_id,
            assembled_bundle_sha256=assembled_sha,
            base_catalog_sha256=base_catalog_sha256,
        )
        conn.commit()
    with psycopg.connect(database_url) as conn:
        open_count = resolve_publish.open_resolution_review_count(
            conn, job_id=job_id
        )
    if open_count > 0:
        with psycopg.connect(database_url) as conn:
            control_plane.write_stage_checkpoint_fenced(
                conn, job_id=job_id, stage="resolve", worker=worker,
                checkpoint={
                    "chapter_stage_version": CHAPTER_STAGE_VERSION,
                    "plan_fingerprint": frozen_plan["plan_fingerprint"],
                    "assembled_bundle_sha256": assembled_sha,
                    "base_catalog_sha256": base_catalog_sha256,
                    "counts": resolve_publish.count_candidates(initials),
                    "open_reviews": open_count,
                    "authoritative": False,
                },
            )
        if on_event is not None:
            on_event(
                "stage_needs_review",
                {"stage": "resolve", "open_reviews": open_count},
            )
        return "needs_review"
    with psycopg.connect(database_url) as conn:
        decisions = resolve_publish.collect_chapter_decisions(conn, job_id=job_id)
    final = resolve_publish.build_final_chapter_resolutions(
        initials, decisions, require_complete=True
    )
    with psycopg.connect(database_url) as conn:
        for resolution in final:
            resolution_store.persist_resolution(conn, resolution)
            conn.commit()
    if _settle_person_state_resolve(
        database_url, job_id=job_id, worker=worker,
        revision_id=revision_id, final=final,
        base_catalog_sha256=base_catalog_sha256, on_event=on_event,
    ) == "needs_review":
        return "needs_review"
    with psycopg.connect(database_url) as conn:
        control_plane.write_stage_checkpoint_fenced(
            conn, job_id=job_id, stage="resolve", worker=worker,
            checkpoint={
                "chapter_stage_version": CHAPTER_STAGE_VERSION,
                "plan_fingerprint": frozen_plan["plan_fingerprint"],
                "assembled_bundle_sha256": assembled_sha,
                "base_catalog_sha256": base_catalog_sha256,
                "final_shas": sorted(sha256_json(item) for item in final),
                "counts": resolve_publish.count_candidates(final),
                "open_reviews": 0,
                "authoritative": False,
            },
        )
        control_plane.advance_stage_fenced(
            conn, job_id=job_id, stage="resolve",
            status="completed", worker=worker,
        )
    if on_event is not None:
        on_event("stage_completed", {"stage": "resolve"})
    return "ok"


def execute_chapter_resolve(
    database_url: str,
    *,
    job_id: uuid.UUID,
    worker: str,
    plan: dict[str, Any],
    lease_seconds: int,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> str:
    """Resolve chapters against the published corpus under a frozen plan.

    First run persists the staged bundle plus the v0.2 initial
    resolutions, freezes the mixed review plan, opens one review item
    per candidate, and parks in ``needs_review`` while any candidate is
    still open. Resume after human review reuses the recorded frozen
    plan exactly — never rebuilding or re-ranking it even when the
    corpus moved — finalizes the same frozen artifacts from the
    recorded decisions, and completes the stage. A job with zero
    candidates proceeds unattended.
    """
    _heartbeat(
        database_url, job_id=job_id, worker=worker,
        lease_seconds=lease_seconds,
    )
    bundle, revision_id, chapter_by_ref = _read_assembled_bundle(
        database_url, job_id
    )
    assembled_sha = sha256_json(bundle)
    stored = _read_plan_output(database_url, job_id)
    if stored is not None:
        # Resume reuses the frozen plan exactly: no rebuild, no re-rank,
        # no new catalog baseline is adopted here. Staleness against a
        # moved baseline is detected at publish time (fail closed).
        frozen_plan = stored.get("plan")
        if not isinstance(frozen_plan, dict) or not frozen_plan:
            raise PersistenceError(
                f"job {job_id} recorded chapter plan output is missing "
                "the frozen plan"
            )
        if stored.get("assembled_bundle_sha256") != assembled_sha:
            raise PersistenceError(
                f"job {job_id} recorded plan binds a different assembled "
                "bundle; refusing to resolve from conflicting bytes"
            )
        initials = _read_resolutions_by_sha(
            database_url, list(stored.get("initial_shas") or [])
        )
        return _settle_resolve(
            database_url, job_id=job_id, worker=worker,
            revision_id=revision_id, frozen_plan=frozen_plan,
            initials=initials, assembled_sha=assembled_sha,
            base_catalog_sha256=stored.get("base_catalog_sha256"),
            on_event=on_event,
        )
    new_label = resolve_publish.new_bundle_label(revision_id)
    by_id = chapter_index_by_id(plan)
    with psycopg.connect(database_url) as conn:
        corpus = resolve_publish.read_corpus_bundles(conn)
        latest = resolve_publish.read_latest_catalog(conn)
    # Pure compute with no connection open.
    initials = resolve_publish.build_chapter_initial_resolutions(
        bundle=bundle, bundle_label=new_label,
        chapter_by_ref=chapter_by_ref,
        chapter_index_by_id=by_id, corpus=corpus,
    )
    base_catalog_sha256 = sha256_json(latest) if latest is not None else sha256_json(None)
    assembled_sha = sha256_json(bundle)
    frozen_plan = resolve_publish.create_chapter_review_plan(
        job_id=job_id, revision_id=revision_id,
        assembled_bundle_sha256=assembled_sha,
        base_catalog_sha256=base_catalog_sha256,
        initial_resolutions=initials, catalog=latest,
        chapter_by_ref=chapter_by_ref,
    )
    # Durable, idempotent persistence; resume reuses every row.
    with psycopg.connect(database_url) as conn:
        staged_store.persist_bundle(conn, new_label, bundle)
        conn.commit()
    with psycopg.connect(database_url) as conn:
        resolve_publish.persist_chapter_initial_resolutions(conn, initials)
        conn.commit()
    with psycopg.connect(database_url) as conn:
        control_plane.record_output_fenced(
            conn, job_id=job_id, revision_id=revision_id,
            worker=worker, artifact_type=CHAPTER_PLAN_OUTPUT_TYPE,
            artifact_sha256=sha256_json(frozen_plan),
            payload={
                "plan": frozen_plan,
                "plan_fingerprint": frozen_plan["plan_fingerprint"],
                "assembled_bundle_sha256": assembled_sha,
                "base_catalog_sha256": base_catalog_sha256,
                "initial_shas": sorted(
                    resolve_publish.initial_artifact_sha(item) for item in initials
                ),
            },
        )
        conn.commit()
    return _settle_resolve(
        database_url, job_id=job_id, worker=worker,
        revision_id=revision_id, frozen_plan=frozen_plan,
        initials=initials, assembled_sha=assembled_sha,
        base_catalog_sha256=base_catalog_sha256, on_event=on_event,
    )


def execute_chapter_present(
    database_url: str,
    *,
    job_id: uuid.UUID,
    worker: str,
    plan: dict[str, Any],
    lease_seconds: int,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> str:
    """Verify the published chapters without re-translating anything.

    Every planned chapter must have exactly one publication bound to
    its accepted artifact/revision; the publication payload must carry
    the complete ordered translation blocks (never a blurb or a
    first-paragraph summary). A 0.2 book must additionally expose one
    reading stream that binds exactly these publications, so ``present``
    never verifies chapters while a partial reading index is public.
    Optional person/event presentations stay independent: they neither
    block nor substitute for the complete translation here.
    """
    _heartbeat(
        database_url, job_id=job_id, worker=worker,
        lease_seconds=lease_seconds,
    )
    with psycopg.connect(database_url) as conn:
        accepted = chapter_store.read_accepted_chapters(conn, job_id=job_id)
        published = chapter_store.list_published_chapters(conn, job_id=job_id, limit=100)
    expected = {entry["chapter_id"]: entry for entry in accepted}
    if len(expected) != int(plan["chapter_count"]):
        raise PersistenceError(
            f"job {job_id} accepted {len(expected)} chapters but the plan "
            f"expects {plan['chapter_count']}; refusing a partial present"
        )
    by_artifact = {entry["artifact_sha256"]: entry for entry in accepted}
    seen: set[str] = set()
    for item in published:
        entry = by_artifact.get(item["artifact_sha256"])
        if entry is None:
            raise PersistenceError(
                f"job {job_id} publication {item['publication_id']} binds "
                "an artifact outside this job/revision; refusing present"
            )
        with psycopg.connect(database_url) as conn:
            full = chapter_store.read_published_chapter(
                conn, publication_id=uuid.UUID(item["publication_id"])
            )
        publication = full.get("publication") or {}
        blocks = publication.get("translation_blocks")
        if not isinstance(blocks, list) or not blocks:
            raise PersistenceError(
                f"job {job_id} publication {item['publication_id']} carries "
                "no complete translation blocks; refusing to present a "
                "summary as the full text"
            )
        seen.add(item["chapter_id"])
    missing = sorted(set(expected) - seen)
    if missing:
        raise PersistenceError(
            f"job {job_id} chapters {missing} have no publication; "
            "refusing to present before atomic publish"
        )
    # A 0.2 book must also expose its immutable reading stream in the same
    # publication: present verifies the stream binds exactly this job's
    # published chapters (never a second/partial reading index).
    reading_stream_id: str | None = None
    accepted_versions = {entry["artifact"].get("version") for entry in accepted}
    if accepted_versions in ({"0.2"}, {"0.3"}):
        with psycopg.connect(database_url) as conn:
            stream_row = conn.execute(
                """
                SELECT stream_id, chapter_publication_ids, unit_count, group_count
                FROM chronicle.reading_streams WHERE revision_id = %s
                """,
                (uuid.UUID(str(plan["revision_id"])),),
            ).fetchone()
        if stream_row is None:
            raise PersistenceError(
                f"job {job_id} published reading chapters but has no reading "
                "stream; refusing present"
            )
        stream_ids = {str(value) for value in stream_row[1]}
        published_ids = {
            item["publication_id"] for item in published if item["chapter_id"] in expected
        }
        if stream_ids != published_ids:
            raise PersistenceError(
                f"job {job_id} reading stream {stream_row[0]} binds "
                "different chapter publications; refusing present"
            )
        if int(stream_row[2]) < 1 or int(stream_row[3]) < 1:
            raise PersistenceError(
                f"job {job_id} reading stream {stream_row[0]} carries no "
                "units/groups; refusing present"
            )
        reading_stream_id = str(stream_row[0])
        if accepted_versions == {"0.3"}:
            # A 0.3 book must also expose exactly one immutable person-state
            # manifest bound to this stream and its complete publication set;
            # present never verifies chapters while the state index is partial.
            with psycopg.connect(database_url) as conn:
                state_row = conn.execute(
                    """
                    SELECT m.manifest_sha, m.chapter_publication_ids, m.assessment_hashes,
                           (SELECT count(*) FROM chronicle.person_state_unit_people p
                             WHERE p.manifest_sha = m.manifest_sha) AS people,
                           (SELECT count(*) FROM chronicle.person_state_items i
                             WHERE i.manifest_sha = m.manifest_sha) AS items
                    FROM chronicle.person_state_manifests m
                    WHERE m.stream_id = %s
                    """,
                    (uuid.UUID(reading_stream_id),),
                ).fetchone()
            if state_row is None:
                raise PersistenceError(
                    f"job {job_id} published 0.3 chapters but has no person-state "
                    "manifest; refusing present"
                )
            state_publications = {str(value) for value in state_row[1]}
            if state_publications != stream_ids:
                raise PersistenceError(
                    f"job {job_id} person-state manifest {state_row[0]} does not "
                    "bind the stream's chapter publications; refusing present"
                )
            if not state_row[2]:
                raise PersistenceError(
                    f"job {job_id} person-state manifest {state_row[0]} cites no "
                    "reviewed assessment; refusing present"
                )
            if int(state_row[3]) < 0 or int(state_row[4]) < 0:
                raise PersistenceError(
                    f"job {job_id} person-state manifest {state_row[0]} index is invalid; "
                    "refusing present"
                )
    with psycopg.connect(database_url) as conn:
        control_plane.write_stage_checkpoint_fenced(
            conn, job_id=job_id, stage="present", worker=worker,
            checkpoint={
                "chapter_stage_version": CHAPTER_STAGE_VERSION,
                "chapter_count": len(expected),
                "publication_ids": sorted(
                    item["publication_id"] for item in published
                    if item["chapter_id"] in expected
                ),
                "reading_stream_id": reading_stream_id,
                "person_state_manifest_sha": (
                    state_row[0] if accepted_versions == {"0.3"} else None
                ),
                "verified_only": True,
                "authoritative": False,
            },
        )
        control_plane.advance_stage_fenced(
            conn, job_id=job_id, stage="present",
            status="completed", worker=worker,
        )
    if on_event is not None:
        on_event("stage_completed", {"stage": "present"})
    return "ok"


# ---------------------------------------------------------------------------
# Job input loading (revision bytes -> plan -> program-owned requests)
# ---------------------------------------------------------------------------


def load_chapter_inputs(
    database_url: str,
    *,
    job_id: uuid.UUID,
    revision_source: Callable[[uuid.UUID], tuple[str, str] | None],
    limits: chapter_contract.ChapterLimits,
    candidate_version: str | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Load and plan the immutable revision text for a job.

    Returns ``(text, binding, plan, requests)``. The source callback's
    byte hash is verified against the immutable revision row before the
    T03 plan is accepted; any drift fails closed instead of planning
    the wrong bytes. Pure compute apart from short verification reads:
    no transaction is held open across the source callback.

    ``candidate_version`` defaults to the 0.1 first-round generation so
    existing callers are unchanged; the worker selects the model's version
    through :func:`candidate_version_for_model` so a reading run plans 0.2.
    """
    # No connection is open across this call: a slow source read holds
    # no row lock and hides no lease expiry.
    loaded = revision_source(job_id)
    if loaded is None:
        raise PersistenceError(
            "chapter production requires the revision source text; "
            "refusing deterministic fake chapters"
        )
    text, source_sha256 = loaded
    with psycopg.connect(database_url) as conn:
        binding = read_revision_binding(conn, job_id=job_id)
    if binding["source_sha256"] != source_sha256:
        raise PersistenceError(
            f"revision source for job {job_id} failed verification: "
            "callback hash does not match the immutable revision row "
            "(refusing to plan bytes the revision does not own)"
        )
    plan, requests = plan_job_chapters(
        text=text, source_sha256=source_sha256,
        binding=binding, limits=limits,
        candidate_version=candidate_version,
    )
    return text, binding, plan, requests


# ---------------------------------------------------------------------------
# Structure / segment over the frozen chapter plan
# ---------------------------------------------------------------------------


def execute_chapter_structure(
    database_url: str,
    *,
    job_id: uuid.UUID,
    worker: str,
    plan: dict[str, Any],
    text: str,
    lease_seconds: int,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> str:
    """Persist the T03 plan as sections plus one chunk per chapter."""
    with psycopg.connect(database_url) as conn:
        ensure_chapter_topology(
            conn, job_id=job_id, worker=worker, plan=plan, text=text
        )
        conn.commit()
    with psycopg.connect(database_url) as conn:
        control_plane.write_stage_checkpoint_fenced(
            conn, job_id=job_id, stage="structure", worker=worker,
            checkpoint={
                "chapter_stage_version": CHAPTER_STAGE_VERSION,
                "plan_version": plan["version"],
                "plan_sha256": plan["plan_sha256"],
                "chapter_count": plan["chapter_count"],
                "chapters": [
                    {
                        "chapter_id": chapter["chapter_id"],
                        "chapter_index": chapter["chapter_index"],
                        "title": chapter.get("title"),
                        "start": chapter["start"],
                        "end": chapter["end"],
                    }
                    for chapter in plan["chapters"]
                ],
            },
        )
        control_plane.advance_stage_fenced(
            conn, job_id=job_id, stage="structure",
            status="completed", worker=worker,
        )
    if on_event is not None:
        on_event("stage_completed", {"stage": "structure"})
    return "ok"


def execute_chapter_segment(
    database_url: str,
    *,
    job_id: uuid.UUID,
    worker: str,
    plan: dict[str, Any],
    requests: list[dict[str, Any]],
    lease_seconds: int,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> str:
    """Record one chapter locator checkpoint per chunk (no model calls)."""
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            """
            SELECT chunk_id, chunk_index FROM chronicle.ingestion_chunks
            WHERE job_id = %s ORDER BY chunk_index
            """,
            (job_id,),
        ).fetchall()
    if [int(row[1]) for row in rows] != list(range(plan["chapter_count"])):
        raise PersistenceError(
            f"job {job_id} chapter chunks do not match the planned "
            f"{plan['chapter_count']} chapters; refusing to segment on a "
            "stale chunk set (run the structure stage first)"
        )
    for chunk_id, chunk_index in rows:
        request = requests[int(chunk_index)]
        with psycopg.connect(database_url) as conn:
            control_plane.write_chunk_checkpoint_fenced(
                conn, job_id=job_id, chunk_id=chunk_id, worker=worker,
                checkpoint={
                    "chapter_stage_version": CHAPTER_STAGE_VERSION,
                    "chapter_id": request["chapter_id"],
                    "chapter_index": int(chunk_index),
                    "plan_sha256": plan["plan_sha256"],
                    "plan_version": plan["version"],
                    "request_fingerprint": chapter_contract.request_fingerprint(
                        request
                    ),
                },
            )
    with psycopg.connect(database_url) as conn:
        control_plane.write_stage_checkpoint_fenced(
            conn, job_id=job_id, stage="segment", worker=worker,
            checkpoint={
                "chapter_stage_version": CHAPTER_STAGE_VERSION,
                "plan_sha256": plan["plan_sha256"],
                "chunk_count": len(rows),
            },
        )
        control_plane.advance_stage_fenced(
            conn, job_id=job_id, stage="segment",
            status="completed", worker=worker,
        )
    if on_event is not None:
        on_event("stage_completed", {"stage": "segment"})
    return "ok"


# ---------------------------------------------------------------------------
# Publish driver: atomic publish with stale-baseline handling
# ---------------------------------------------------------------------------


def execute_chapter_publish(
    database_url: str,
    *,
    job_id: uuid.UUID,
    worker: str,
    plan: dict[str, Any] | None = None,
    lease_seconds: int,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> str:
    """Publish every accepted chapter atomically; fail closed when stale.

    Returns 'ok'. A moved baseline propagates as
    :class:`resolve_publish.PublicationPlanStale`: the caller parks the
    publish stage and the job in ``failed`` with that evidence while the
    frozen plan stays untouched — never auto-passed or rebuilt.
    Raises :class:`LeaseLost` when this worker no longer holds the lease.

    ``plan`` is the exact T03 chapter plan for this revision. It is
    required when the accepted chapters carry 0.2 reading artifacts, so
    the atomic publish can compile and persist the reading index in the
    same transaction; a 0.1 job ignores it.
    """
    with psycopg.connect(database_url) as conn:
        control_plane.heartbeat_job_strict(
            conn, job_id=job_id, worker=worker,
            lease_seconds=lease_seconds,
        )
    with psycopg.connect(database_url) as conn:
        result = resolve_publish.publish_chapters(
            conn, job_id=job_id, worker=worker, chapter_plan=plan
        )
        conn.commit()
    if on_event is not None:
        on_event("stage_completed", {"stage": "publish", **result})
    return "ok"
