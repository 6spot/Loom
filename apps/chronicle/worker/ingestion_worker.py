"""Durable Chronicle worker for the current staged ingestion contracts.

PostgreSQL remains the only queue and lease authority.  The worker claims a
job, advances the existing eight-stage state machine, and commits every
mutation in a short transaction.  Chapter jobs always use the natural-
chapter staged 0.4 pipeline; narrative jobs explicitly own only ``present``.
There is no compatibility executor or synthetic completion path in this
module.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import signal
import socket
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

_PERSISTENCE_DIR = Path(__file__).resolve().parent.parent / "persistence"
_WORKER_DIR = Path(__file__).resolve().parent
for _path in (str(_PERSISTENCE_DIR), str(_WORKER_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import control_plane  # noqa: E402
import chapter_stage  # noqa: E402
import documents  # noqa: E402
import narrative_stage  # noqa: E402
import person_history_stage  # noqa: E402
import studio_production  # noqa: E402
from common import LeaseLost, PersistenceConflict, PersistenceError  # noqa: E402

try:
    import psycopg  # noqa: E402
except ImportError as exc:  # pragma: no cover - deployment vendors psycopg
    raise PersistenceError(
        "the Chronicle worker requires psycopg "
        "(apps/chronicle/worker/requirements.txt)"
    ) from exc


WORKER_VERSION = "0.4"
DEFAULT_LEASE_SECONDS = 300
DEFAULT_POLL_INTERVAL_SECONDS = 5.0


def default_worker_id() -> str:
    """Return a unique worker identity for lease ownership."""
    return f"worker-{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def database_url_from_env(explicit: str | None = None) -> str:
    """Resolve the Chronicle database URL (explicit flag wins over env)."""
    url = explicit or os.environ.get("CHRONICLE_DATABASE_URL")
    if not url:
        raise PersistenceError(
            "Chronicle database URL is required via --database-url or "
            "CHRONICLE_DATABASE_URL"
        )
    return url


def source_dir_from_env(explicit: str | None = None) -> Path | None:
    """Resolve the Chronicle-owned revision storage directory.

    A missing directory is represented as ``None`` so the formal production
    entry can reject the configuration before claiming work.  The worker
    itself never turns that absence into generated content.
    """
    if explicit:
        return Path(explicit).expanduser()
    raw = (os.environ.get("CHRONICLE_SOURCE_DIR") or "").strip()
    return Path(raw).expanduser() if raw else None


def build_revision_source(
    database_url: str, storage_dir: Path | str
) -> Callable[[uuid.UUID], tuple[str, str]]:
    """Build a hash-verifying revision text loader for production jobs."""
    base = Path(storage_dir).expanduser()

    def source(job_id: uuid.UUID) -> tuple[str, str]:
        with psycopg.connect(database_url) as conn:
            job = conn.execute(
                "SELECT revision_id FROM chronicle.ingestion_jobs "
                "WHERE job_id = %s",
                (job_id,),
            ).fetchone()
            if job is None:
                raise PersistenceError(f"unknown job {job_id}")
            revision = conn.execute(
                "SELECT source_sha256, storage_key "
                "FROM chronicle.document_revisions WHERE revision_id = %s",
                (job[0],),
            ).fetchone()
            if revision is None:
                raise PersistenceError(
                    f"unknown revision {job[0]} for job {job_id}"
                )
            expected_sha, storage_key = revision
        data = documents.read_revision_bytes(base, storage_key)
        actual_sha = hashlib.sha256(data).hexdigest()
        if actual_sha != expected_sha:
            raise PersistenceError(
                f"source file for revision {job[0]} failed verification: "
                "stored bytes do not match the immutable revision hash"
            )
        text = documents.decode_source(data)
        if text == "":
            raise PersistenceError(
                f"revision {job[0]} normalizes to empty text; nothing to process"
            )
        return text, expected_sha

    return source


def _safe_error(exc: BaseException, context: str) -> str:
    """Return bounded diagnostics without exposing model/provider payloads."""
    if isinstance(exc, PersistenceError):
        message = " ".join(str(exc).split())[:6000]
        return f"{context}: {message}" if message else context
    return f"{context} ({type(exc).__name__})"


class JobRunner:
    """Execute one claimed current chapter or narrative job."""

    def __init__(
        self,
        database_url: str,
        *,
        worker: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        stop: threading.Event | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        revision_source: Callable[[uuid.UUID], tuple[str, str] | None] | None = None,
        chapter_model: Any | None = None,
        chapter_limits: Any | None = None,
        narrative_model: Any | None = None,
    ) -> None:
        if not isinstance(worker, str) or not worker:
            raise PersistenceError("worker must be a non-empty string")
        if not isinstance(lease_seconds, int) or lease_seconds < 1:
            raise PersistenceError("lease_seconds must be a positive integer")
        if chapter_limits is not None and not isinstance(
            chapter_limits, chapter_stage.chapter_contract.ChapterLimits
        ):
            raise PersistenceError(
                "chapter_limits must be a chapter_contract.ChapterLimits"
            )
        self.database_url = database_url
        self.worker = worker
        self.lease_seconds = lease_seconds
        self.stop = stop or threading.Event()
        self.on_event = on_event
        self.revision_source = revision_source
        self.chapter_model = chapter_model
        self.chapter_limits = chapter_limits or chapter_stage.chapter_contract.ChapterLimits()
        self.narrative_model = narrative_model
        self._chapter_inputs_cache: dict[
            uuid.UUID,
            tuple[str, dict[str, Any], dict[str, Any], list[dict[str, Any]]],
        ] = {}

    def _read_job(self, job_id: uuid.UUID) -> tuple[str, int, int, uuid.UUID]:
        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                "SELECT status, attempt, max_attempts, revision_id "
                "FROM chronicle.ingestion_jobs WHERE job_id = %s",
                (job_id,),
            ).fetchone()
        if row is None:
            raise PersistenceError(f"unknown job {job_id}")
        return row[0], int(row[1]), int(row[2]), row[3]

    def _read_stage(self, job_id: uuid.UUID, stage: str) -> str:
        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                "SELECT status FROM chronicle.ingestion_job_stages "
                "WHERE job_id = %s AND stage = %s",
                (job_id, stage),
            ).fetchone()
        if row is None:
            raise PersistenceError(f"unknown stage {stage!r} for job {job_id}")
        return row[0]

    def _heartbeat(self, job_id: uuid.UUID) -> None:
        with psycopg.connect(self.database_url) as conn:
            control_plane.heartbeat_job_strict(
                conn,
                job_id=job_id,
                worker=self.worker,
                lease_seconds=self.lease_seconds,
            )

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self.on_event is not None:
            self.on_event(event, payload)

    def check_halt(self, job_id: uuid.UUID) -> str | None:
        """Return a halt outcome when cancellation or an external decision won."""
        if self.stop.is_set():
            return "stopped"
        status = self._read_job(job_id)[0]
        if status == "cancelled":
            return "cancelled"
        if status != "running":
            return "stopped"
        return None

    def _read_job_kind(self, job_id: uuid.UUID) -> tuple[str, dict[str, Any] | None]:
        """Decode the chapter, narrative, and person-history job markers."""
        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                "SELECT checkpoint FROM chronicle.ingestion_jobs WHERE job_id = %s",
                (job_id,),
            ).fetchone()
        if row is None:
            raise PersistenceError(f"unknown job {job_id}")
        checkpoint = row[0]
        if checkpoint == {}:
            return "chapter", None
        if not isinstance(checkpoint, dict):
            raise PersistenceError("unsupported ingestion job type")
        if set(checkpoint) == {"person_history_scope"}:
            kind = "person_history"
            scope = checkpoint.get("person_history_scope")
            person_id = scope.get("person_id") if isinstance(scope, dict) else None
            if not isinstance(person_id, str) or not person_id:
                raise PersistenceError("person-history job has an invalid canonical person")
        elif set(checkpoint) == {"narrative_scope"}:
            kind = "narrative"
            scope = checkpoint.get("narrative_scope")
        else:
            raise PersistenceError("unsupported ingestion job type")
        if not isinstance(scope, dict):
            raise PersistenceError(f"{kind} job has an invalid source scope")
        catalog_sha = scope.get("catalog_sha")
        publication_ids = scope.get("publication_ids")
        if (
            not isinstance(catalog_sha, str)
            or not catalog_sha
            or not isinstance(publication_ids, list)
            or not publication_ids
            or any(not isinstance(value, str) or not value for value in publication_ids)
            or len(set(publication_ids)) != len(publication_ids)
        ):
            raise PersistenceError(f"{kind} job has an invalid source scope")
        return kind, scope

    def _chapter_config_error(self) -> str | None:
        if self.revision_source is None:
            return (
                "chapter production requires the revision source; "
                "refusing to manufacture chapter output"
            )
        if self.chapter_model is None:
            return (
                "chapter production requires the staged 0.4 provider; "
                "refusing to manufacture chapter output"
            )
        if getattr(self.chapter_model, "candidate_version", None) != "0.4":
            return "chapter production requires the staged 0.4 provider"
        if not callable(getattr(self.chapter_model, "model_for", None)) or not callable(
            getattr(self.chapter_model, "public_config", None)
        ):
            return "chapter production requires a complete staged provider configuration"
        return None

    def _narrative_config_error(self) -> str | None:
        if self.revision_source is None:
            return "narrative production requires the revision source"
        graph_provider = isinstance(getattr(self.narrative_model, "steps", None), dict) and callable(
            getattr(self.narrative_model, "model_for", None)
        )
        if graph_provider:
            return None
        if not callable(getattr(self.narrative_model, "complete", None)) or not getattr(self.narrative_model, "name", None):
            return "narrative production requires a configured provider"
        return None

    def _validate_job_shape(self, job_id: uuid.UUID, kind: str) -> str | None:
        with psycopg.connect(self.database_url) as conn:
            rows = dict(
                conn.execute(
                    "SELECT stage, status FROM chronicle.ingestion_job_stages "
                    "WHERE job_id = %s",
                    (job_id,),
                ).fetchall()
            )
        if set(rows) != set(control_plane.STAGE_NAMES):
            return "job has an incomplete stage topology"
        if kind in ("narrative", "person_history"):
            if rows.get("present") == "skipped":
                return f"{kind} job must own the present stage"
            if any(rows[stage] != "skipped" for stage in control_plane.STAGE_NAMES if stage != "present"):
                return f"{kind} job owns only present"
        elif any(status == "skipped" for status in rows.values()):
            return "chapter job carries an unsupported skipped stage"
        return None

    def _load_chapter_inputs(
        self, job_id: uuid.UUID
    ) -> tuple[str, dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        cached = self._chapter_inputs_cache.get(job_id)
        if cached is not None:
            return cached
        if self.revision_source is None or self.chapter_model is None:
            raise PersistenceError(
                "chapter production requires the revision source and staged provider"
            )
        loaded = chapter_stage.load_chapter_inputs(
            self.database_url,
            job_id=job_id,
            revision_source=self.revision_source,
            limits=self.chapter_limits,
            candidate_version="0.4",
        )
        self._chapter_inputs_cache[job_id] = loaded
        return loaded

    def _execute_prepare(self, job_id: uuid.UUID) -> str:
        """Persist real preparation metadata without creating output content."""
        self._heartbeat(job_id)
        _text, binding, plan, requests = self._load_chapter_inputs(job_id)
        config = self.chapter_model.public_config()
        if not isinstance(config, dict):
            raise PersistenceError("staged provider returned an invalid public configuration")
        checkpoint = {
            "worker_version": WORKER_VERSION,
            "chapter_stage_version": chapter_stage.CHAPTER_STAGE_VERSION,
            "plan_version": plan["version"],
            "plan_sha256": plan["plan_sha256"],
            "chapter_count": plan["chapter_count"],
            "revision_id": str(binding["revision_id"]),
            "source_sha256": binding["source_sha256"],
            "normalized_sha256": plan.get("normalized_sha256"),
            "candidate_version": "0.4",
            "request_count": len(requests),
            "model_config": config,
        }
        with psycopg.connect(self.database_url) as conn:
            control_plane.write_stage_checkpoint_fenced(
                conn, job_id=job_id, stage="prepare", worker=self.worker,
                checkpoint=checkpoint,
            )
            control_plane.advance_stage_fenced(
                conn, job_id=job_id, stage="prepare", status="completed",
                worker=self.worker,
            )
        self._emit("stage_completed", {"stage": "prepare"})
        return "ok"

    def _execute_chapter_stage(self, job_id: uuid.UUID, stage: str) -> str:
        _text, _binding, plan, requests = self._load_chapter_inputs(job_id)
        if stage == "structure":
            return chapter_stage.execute_chapter_structure(
                self.database_url, job_id=job_id, worker=self.worker, plan=plan,
                text=_text, lease_seconds=self.lease_seconds, on_event=self._emit,
            )
        if stage == "segment":
            return chapter_stage.execute_chapter_segment(
                self.database_url, job_id=job_id, worker=self.worker, plan=plan,
                requests=requests, lease_seconds=self.lease_seconds, on_event=self._emit,
            )
        if stage == "extract":
            with psycopg.connect(self.database_url) as conn:
                production_request = studio_production.read_request(conn, job_id)
            selected_model = self.chapter_model
            selection = production_request.get("model_selection") if production_request else None
            if selection is not None:
                if not callable(getattr(selected_model, "for_selection", None)):
                    raise PersistenceError("task model selection requires the staged provider")
                selected_model = selected_model.for_selection(selection)
            return chapter_stage.execute_chapter_extract(
                self.database_url, job_id=job_id, worker=self.worker, plan=plan,
                requests=requests, model=selected_model, limits=self.chapter_limits,
                lease_seconds=self.lease_seconds, on_event=self._emit,
                halt=self.check_halt,
            )
        if stage == "assemble":
            chapter_stage.execute_chapter_assemble(
                self.database_url, job_id=job_id, worker=self.worker, plan=plan,
                lease_seconds=self.lease_seconds, on_event=self._emit,
            )
            return "ok"
        if stage == "resolve":
            return chapter_stage.execute_chapter_resolve(
                self.database_url, job_id=job_id, worker=self.worker, plan=plan,
                lease_seconds=self.lease_seconds, on_event=self._emit,
            )
        if stage == "publish":
            return chapter_stage.execute_chapter_publish(
                self.database_url, job_id=job_id, worker=self.worker, plan=plan,
                lease_seconds=self.lease_seconds, on_event=self._emit,
            )
        if stage == "present":
            return chapter_stage.execute_chapter_present(
                self.database_url, job_id=job_id, worker=self.worker, plan=plan,
                lease_seconds=self.lease_seconds, on_event=self._emit,
            )
        raise PersistenceError(f"chapter pipeline owns no executor for stage {stage!r}")

    def _complete_stage_if_needed(self, job_id: uuid.UUID, stage: str) -> None:
        if self._read_stage(job_id, stage) in ("completed", "skipped"):
            return
        with psycopg.connect(self.database_url) as conn:
            control_plane.advance_stage_fenced(
                conn, job_id=job_id, stage=stage, status="completed",
                worker=self.worker,
            )
        self._emit("stage_completed", {"stage": stage})

    def _fail(self, job_id: uuid.UUID, stage: str | None, exc: BaseException, *, context: str) -> str:
        error = _safe_error(exc, context)
        stage_status = self._read_stage(job_id, stage) if stage is not None else None
        with psycopg.connect(self.database_url) as conn:
            if stage is not None and stage_status not in ("completed", "skipped"):
                control_plane.advance_stage_fenced(
                    conn, job_id=job_id, stage=stage, status="failed",
                    worker=self.worker, error=error,
                )
            control_plane.set_job_status_fenced(
                conn, job_id=job_id, status="failed", worker=self.worker, error=error,
            )
        self._emit("job_failed", {"job_id": str(job_id), "error": error})
        return "failed"

    def _park_review(self, job_id: uuid.UUID, stage: str, outcome: str) -> str:
        if stage == "extract":
            with psycopg.connect(self.database_url) as conn:
                content_gate = conn.execute(
                    "SELECT 1 FROM chronicle.review_items WHERE job_id = %s "
                    "AND status = 'open' AND payload->>'scope' = 'chapter_content' LIMIT 1",
                    (job_id,),
                ).fetchone() is not None
                if not content_gate:
                    control_plane.open_review_item(
                        conn, job_id=job_id, kind="chunk_failure",
                        payload={"stage": stage, "worker": self.worker},
                    )
            reason = "chapter content review pending" if content_gate else "chapter attempts exhausted; awaiting review"
        else:
            reason = f"{stage} review pending; awaiting human decisions"
        stage_status = self._read_stage(job_id, stage)
        with psycopg.connect(self.database_url) as conn:
            if stage_status not in ("needs_review", "completed", "skipped"):
                control_plane.advance_stage_fenced(
                    conn, job_id=job_id, stage=stage, status="needs_review",
                    worker=self.worker, error=reason,
                )
            control_plane.set_job_status_fenced(
                conn, job_id=job_id, status="needs_review", worker=self.worker,
                error=reason,
            )
        self._emit("stage_needs_review", {"stage": stage, "outcome": outcome})
        return "needs_review"

    def execute_job(self, job_id: uuid.UUID) -> str:
        try:
            return self._execute_job(job_id)
        except LeaseLost:
            self._emit("lease_lost", {"job_id": str(job_id)})
            return "lease_lost"

    def _execute_job(self, job_id: uuid.UUID) -> str:
        halt = self.check_halt(job_id)
        if halt is not None:
            return halt
        try:
            kind, scope = self._read_job_kind(job_id)
        except Exception as exc:
            return self._fail(job_id, None, exc, context="job validation failed")
        shape_error = self._validate_job_shape(job_id, kind)
        if shape_error:
            return self._fail(job_id, None, PersistenceError(shape_error), context="job validation failed")
        config_error = self._narrative_config_error() if kind in ("narrative", "person_history") else self._chapter_config_error()
        if config_error is not None:
            return self._fail(job_id, None, PersistenceError(config_error), context="job configuration failed")

        for stage in control_plane.STAGE_NAMES:
            halt = self.check_halt(job_id)
            if halt is not None:
                return halt
            stage_status = self._read_stage(job_id, stage)
            if stage_status in ("completed", "skipped"):
                continue
            if stage_status in ("pending", "failed", "needs_review"):
                with psycopg.connect(self.database_url) as conn:
                    control_plane.advance_stage_fenced(
                        conn, job_id=job_id, stage=stage, status="running",
                        worker=self.worker,
                    )
            self._heartbeat(job_id)
            try:
                if kind in ("narrative", "person_history"):
                    if stage != "present":
                        raise PersistenceError(f"{kind} job owns only present")
                    selected_model = self.narrative_model
                    with psycopg.connect(self.database_url) as conn:
                        production_request = studio_production.read_request(conn, job_id)
                    selection = production_request.get("model_selection") if production_request else None
                    if selection is not None:
                        if not callable(getattr(selected_model, "for_selection", None)):
                            raise PersistenceError(f"{kind} task model selection requires the narrative provider")
                        selected_model = selected_model.for_selection(selection)
                    if kind == "person_history":
                        outcome = person_history_stage.execute(
                            self.database_url, job_id=job_id, worker=self.worker,
                            revision_source=self.revision_source, model=selected_model,
                            lease_seconds=self.lease_seconds, scope=scope,
                            on_event=self._emit,
                        )
                    else:
                        outcome = narrative_stage.execute(
                            self.database_url, job_id=job_id, worker=self.worker,
                            revision_source=self.revision_source, model=selected_model,
                            lease_seconds=self.lease_seconds, scope=scope,
                        )
                elif stage == "prepare":
                    outcome = self._execute_prepare(job_id)
                else:
                    outcome = self._execute_chapter_stage(job_id, stage)
            except LeaseLost:
                raise
            except Exception as exc:
                return self._fail(job_id, stage, exc, context=f"{kind} {stage} failed")

            if outcome == "ok":
                self._complete_stage_if_needed(job_id, stage)
                continue
            if outcome == "needs_review":
                return self._park_review(job_id, stage, outcome)
            if outcome == "failed":
                return self._fail(
                    job_id, stage, PersistenceError("stage failed closed"),
                    context=f"{kind} {stage} failed",
                )
            return outcome

        halt = self.check_halt(job_id)
        if halt is not None:
            return halt
        self._heartbeat(job_id)
        with psycopg.connect(self.database_url) as conn:
            control_plane.set_job_status_fenced(
                conn, job_id=job_id, status="completed", worker=self.worker,
            )
        self._emit("job_completed", {"job_id": str(job_id)})
        return "completed"


def execute_job(
    conn,
    *,
    job_id: uuid.UUID,
    worker: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    stop: threading.Event | None = None,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    revision_source: Callable[[uuid.UUID], tuple[str, str] | None] | None = None,
    chapter_model: Any | None = None,
    chapter_limits: Any | None = None,
    narrative_model: Any | None = None,
) -> str:
    """Execute a claimed job using the connection's DSN for compatibility."""
    runner = JobRunner(
        conn.info.dsn,
        worker=worker,
        lease_seconds=lease_seconds,
        stop=stop,
        on_event=on_event,
        revision_source=revision_source,
        chapter_model=chapter_model,
        chapter_limits=chapter_limits,
        narrative_model=narrative_model,
    )
    return runner.execute_job(job_id)


def run_once(
    database_url: str,
    *,
    worker: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    stop: threading.Event | None = None,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    job_id: uuid.UUID | None = None,
    revision_source: Callable[[uuid.UUID], tuple[str, str] | None] | None = None,
    chapter_model: Any | None = None,
    chapter_limits: Any | None = None,
    narrative_model: Any | None = None,
) -> tuple[uuid.UUID, str] | None:
    """Claim one queued/expired job and execute only current production paths."""
    stop = stop or threading.Event()
    with psycopg.connect(database_url) as conn:
        claimed = control_plane.claim_job(
            conn, worker=worker, lease_seconds=lease_seconds, job_id=job_id
        )
    if claimed is None:
        return None
    runner = JobRunner(
        database_url,
        worker=worker,
        lease_seconds=lease_seconds,
        stop=stop,
        on_event=on_event,
        revision_source=revision_source,
        chapter_model=chapter_model,
        chapter_limits=chapter_limits,
        narrative_model=narrative_model,
    )
    return claimed, runner.execute_job(claimed)


def run_forever(
    database_url: str,
    *,
    worker: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    max_jobs: int | None = None,
    stop: threading.Event | None = None,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    revision_source: Callable[[uuid.UUID], tuple[str, str] | None] | None = None,
    chapter_model: Any | None = None,
    chapter_limits: Any | None = None,
    narrative_model: Any | None = None,
) -> dict[str, int]:
    """Claim and execute jobs until stopped; return an outcome tally."""
    if poll_interval <= 0:
        raise PersistenceError("poll_interval must be positive")
    if max_jobs is not None and (
        not isinstance(max_jobs, int) or isinstance(max_jobs, bool) or max_jobs < 0
    ):
        raise PersistenceError("max_jobs must be a non-negative integer")
    if max_jobs == 0:
        return {}
    stop = stop or threading.Event()
    tally: dict[str, int] = {}
    completed_jobs = 0
    while not stop.is_set():
        try:
            result = run_once(
                database_url,
                worker=worker,
                lease_seconds=lease_seconds,
                stop=stop,
                on_event=on_event,
                revision_source=revision_source,
                chapter_model=chapter_model,
                chapter_limits=chapter_limits,
                narrative_model=narrative_model,
            )
        except PersistenceConflict:
            result = None
        if result is None:
            if max_jobs is not None and completed_jobs >= max_jobs:
                break
            stop.wait(poll_interval)
            continue
        _, outcome = result
        tally[outcome] = tally.get(outcome, 0) + 1
        completed_jobs += 1
        if max_jobs is not None and completed_jobs >= max_jobs:
            break
    return tally


def install_shutdown_handlers(stop: threading.Event) -> None:
    """Wire SIGTERM/SIGINT to graceful shutdown."""

    def _handle(signum, _frame) -> None:
        print(f"chronicle-worker: signal {signum}; finishing current step...", flush=True)
        stop.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(signum, _handle)
        except (OSError, ValueError):
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chronicle durable staged ingestion worker"
    )
    parser.add_argument("--database-url", default=os.environ.get("CHRONICLE_DATABASE_URL"))
    parser.add_argument(
        "--source-dir", default=None,
        help="Chronicle-owned source directory (else CHRONICLE_SOURCE_DIR); required in production",
    )
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--lease-seconds", type=int, default=DEFAULT_LEASE_SECONDS)
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument("--max-jobs", type=int, default=None)
    return parser
