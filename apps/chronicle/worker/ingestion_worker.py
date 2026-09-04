"""Chronicle C1-T4 durable ingestion worker (standalone Python process).

A restart-safe worker execution model for long-running book ingestion that
never ties work to HTTP request lifetime and needs no external queue
service: PostgreSQL 18 is the only coordinator.

Durability contract (authoritative: the ``chronicle.*`` tables behind
``CHRONICLE_DATABASE_URL`` plus the C1-T1 state machine in
``apps/chronicle/control_plane`` / ``persistence/control_plane.py``):

- Jobs are claimed with ``claim_job`` (``FOR UPDATE SKIP LOCKED``), so at
  most one active worker lease wins each job while independent jobs progress
  concurrently on different workers.
- Every database step runs in its own short, explicitly committed
  transaction. No transaction is ever held across executor work, so a
  long-running (or hung) stage never blocks Studio cancellation, and an
  expired lease row is never locked away from a reclaiming worker's
  ``SKIP LOCKED`` claim.
- Every durable transition commits before the worker proceeds, so each
  checkpoint is visible to other connections at once and survives a crash
  at any point.
- Every worker mutation is lease-fenced: the holding worker only. Losing
  the lease (takeover or cancellation) raises ``LeaseLost`` and the stale
  worker halts instead of writing further state or evidence.
- Stages/chunks already ``completed`` (or ``skipped``) are never re-run on
  resume; retries append ``ingestion_chunk_runs`` rows instead of
  overwriting prior model/debug evidence.
- Bounded retry: a job that consumed ``max_attempts`` claim attempts is
  refused by ``retry_job`` instead of looping forever.
- Cancellation (``cancelled``) stops new work immediately while completed
  checkpoints stay intact for audit.
- Stage executors are deterministic fakes in C1-T4; real
  segmentation/extraction begins in C1-T5/C1-T6 and will plug into
  :class:`StageExecutor` without touching this claim/lease/resume core.

Authority boundary (Architecture Amendment 0006): this worker touches only
``CHRONICLE_DATABASE_URL`` and ``chronicle.*`` control-plane tables. It
never reads or writes Loom Runtime/World/Timeline/Work/Binding state and
never models ingestion work as Loom Scheduler Work.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import signal
import socket
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

# The C1-T1 store lives in the registered application persistence root next
# to this worker (Architecture Amendment 0006). Both ship together in every
# deployment (Dockerfile copies whole apps/chronicle), so a relative
# bootstrap keeps the standalone process importable from any CWD.
_PERSISTENCE_DIR = Path(__file__).resolve().parent.parent / "persistence"
if str(_PERSISTENCE_DIR) not in sys.path:
    sys.path.insert(0, str(_PERSISTENCE_DIR))

import control_plane  # noqa: E402
from common import LeaseLost, PersistenceConflict, PersistenceError  # noqa: E402

import assembly  # noqa: E402
import documents  # noqa: E402
import extraction  # noqa: E402
import segmentation  # noqa: E402
from segmentation import SegmentationConfig  # noqa: E402

try:
    import psycopg  # noqa: E402
except ImportError as exc:  # pragma: no cover - deployment always vendors psycopg
    raise PersistenceError(
        "the Chronicle worker requires psycopg "
        "(apps/chronicle/persistence/requirements.txt)"
    ) from exc

#: Version marker recorded on fake chunk-run checkpoints for audit.
WORKER_VERSION = "0.1"

#: Seconds a claimed lease stays valid without a heartbeat.
DEFAULT_LEASE_SECONDS = 300

#: Idle polling delay between claim attempts when no job is claimable.
DEFAULT_POLL_INTERVAL_SECONDS = 5.0

#: Fake pipeline topology per job: one section, this many chunks.
FAKE_CHUNKS_PER_JOB = 2

#: Stage that owns chunk execution in the deterministic fake pipeline.
CHUNK_BEARING_STAGE = "extract"

#: Stages that the C1-T5 real segmentation path owns when a revision
#: source is available. All other stages keep the deterministic fake
#: executor until their own tasks land.
REAL_SEGMENT_STAGES = ("structure", "segment")

#: Stage that the C1-T7 real source-assembly path owns when real chunk
#: extraction ran (``chunk_model`` set). It reads the accepted per-chunk
#: extraction checkpoints and records one revision-scoped source bundle
#: artifact; without real extraction the stage keeps the fake executor.
REAL_ASSEMBLE_STAGE = "assemble"

#: Fake completion artifact recorded once a job finishes every stage.
FAKE_OUTPUT_TYPE = "fake-pipeline-result"


class StageExecutionError(RuntimeError):
    """Raised by a stage executor when one deterministic fake step fails."""


def default_worker_id() -> str:
    """Return a unique worker identity for lease ownership."""
    return f"worker-{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def database_url_from_env(explicit: str | None = None) -> str:
    """Resolve the Chronicle database URL (explicit flag wins over env)."""
    url = explicit or os.environ.get("CHRONICLE_DATABASE_URL")
    if not url:
        raise PersistenceError(
            "Chronicle database URL is required "
            "via --database-url or CHRONICLE_DATABASE_URL"
        )
    return url


def source_dir_from_env(explicit: str | None = None) -> Path | None:
    """Resolve the Chronicle source directory for real segmentation.

    An explicit ``--source-dir`` wins; otherwise a non-empty
    ``CHRONICLE_SOURCE_DIR`` enables the production revision loader.
    Returns ``None`` when neither is set: the worker keeps the
    deterministic fake path (C1-T4 behavior) instead of guessing where
    sources live.
    """
    if explicit:
        return Path(explicit).expanduser()
    raw = (os.environ.get("CHRONICLE_SOURCE_DIR") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def build_revision_source(
    database_url: str, storage_dir: Path | str
) -> Callable[[uuid.UUID], tuple[str, str]]:
    """Build the production revision loader for real segmentation.

    The returned closure maps ``job_id`` to ``(normalized_text,
    source_sha256)`` by reading the job's immutable revision row, loading
    its exact stored bytes via ``documents.read_revision_bytes``, verifying
    the byte hash against the revision row, and normalizing with
    ``documents.decode_source`` (the same normalization segmentation
    offsets are defined in). Every failure mode fails closed with
    :class:`PersistenceError` — unknown job/revision, missing source file,
    hash mismatch, undecodable bytes, or empty text — so the worker parks
    the job in ``failed`` (bounded Studio retry) instead of silently
    falling back to fake checkpoints.
    """
    base = Path(storage_dir).expanduser()

    def source(job_id: uuid.UUID) -> tuple[str, str]:
        with psycopg.connect(database_url) as conn:
            job = conn.execute(
                """
                SELECT revision_id FROM chronicle.ingestion_jobs
                WHERE job_id = %s
                """,
                (job_id,),
            ).fetchone()
            if job is None:
                raise PersistenceError(f"unknown job {job_id}")
            revision = conn.execute(
                """
                SELECT source_sha256, storage_key
                FROM chronicle.document_revisions
                WHERE revision_id = %s
                """,
                (job[0],),
            ).fetchone()
            if revision is None:
                raise PersistenceError(
                    f"unknown revision {job[0]} for job {job_id}"
                )
            expected_sha, storage_key = revision[0], revision[1]
        data = documents.read_revision_bytes(base, storage_key)
        actual_sha = hashlib.sha256(data).hexdigest()
        if actual_sha != expected_sha:
            raise PersistenceError(
                f"source file for revision {job[0]} failed verification: "
                "stored bytes do not match the immutable revision hash "
                "(refusing to segment bytes the revision does not own)"
            )
        text = documents.decode_source(data)
        if text == "":
            raise PersistenceError(
                f"revision {job[0]} normalizes to empty text; "
                "nothing to segment"
            )
        return text, expected_sha

    return source


class StageExecutor:
    """Deterministic fake stage executor.

    ``fail_plan`` maps a stage name to the number of times that stage must
    fail before it succeeds; ``fail_chunks`` maps a chunk index to the
    number of times that chunk must fail. Both counters decrement per
    attempt, so tests can script exact failure/retry sequences and
    production fakes always succeed. Real C1-T5/C1-T6 executors will
    implement :meth:`execute_stage` / :meth:`execute_chunk` instead.

    Executor code runs with no database transaction open: it receives
    plain values and returns plain checkpoints, so a slow or hung model
    call can never hold a row lock, block cancellation, or hide a lease
    expiry from a reclaiming worker.
    """

    def __init__(
        self,
        fail_plan: dict[str, int] | None = None,
        fail_chunks: dict[int, int] | None = None,
    ) -> None:
        self.fail_plan = dict(fail_plan or {})
        self.fail_chunks = dict(fail_chunks or {})

    def execute_stage(self, stage: str, job_id: uuid.UUID) -> dict[str, Any]:
        """Run one non-chunk stage; raises :class:`StageExecutionError`."""
        remaining = self.fail_plan.get(stage, 0)
        if remaining > 0:
            self.fail_plan[stage] = remaining - 1
            raise StageExecutionError(
                f"fake executor failing stage {stage!r} "
                f"for job {job_id} ({remaining} failure(s) scripted)"
            )
        # Sleep hook for transaction-lifetime probes: tests may set
        # `block_stages = {stage: threading.Event}` to hold executor work
        # open while another connection cancels or takes over the lease.
        event = getattr(self, "block_stages", {}).get(stage)
        if event is not None:
            event.wait(timeout=120)
        return {"worker_version": WORKER_VERSION, "stage": stage}

    def execute_chunk(
        self, chunk_index: int, job_id: uuid.UUID
    ) -> dict[str, Any]:
        """Run one chunk; raises :class:`StageExecutionError`."""
        remaining = self.fail_chunks.get(chunk_index, 0)
        if remaining > 0:
            self.fail_chunks[chunk_index] = remaining - 1
            raise StageExecutionError(
                f"fake executor failing chunk {chunk_index} "
                f"for job {job_id} ({remaining} failure(s) scripted)"
            )
        event = getattr(self, "block_chunks", {}).get(chunk_index)
        if event is not None:
            event.wait(timeout=120)
        return {"worker_version": WORKER_VERSION, "chunk_index": chunk_index}


def _fake_sha(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


class JobRunner:
    """Executes one claimed job using short committed transactions only.

    Every method that touches the database opens its own connection, runs
    exactly one committed transaction, and closes it before returning.
    Executor calls happen strictly between connections, never inside one,
    so hung executor work holds no row lock and hides no checkpoint.
    Every mutation is lease-fenced to this runner's ``worker`` identity;
    losing the lease raises :class:`LeaseLost` and halts execution.

    ``revision_source`` is the C1-T5 opt-in hook: ``revision_source(job_id)``
    returns ``(normalized_text, source_sha256)`` for the job's revision, or
    ``None`` to keep the deterministic fake path. When text is available,
    the ``structure``/``segment`` stages persist the real versioned
    segmentation (sections, chunks, context checkpoints) instead of fake
    executor checkpoints; every other stage is untouched, and jobs without
    a source behave exactly as in C1-T4.

    ``chunk_model`` is the C1-T6 opt-in hook: an object with
    ``complete(prompt) -> str`` and ``name`` (the
    :mod:`extraction` provider protocol). When set *and* ``revision_source``
    supplies the revision text, the ``extract`` stage runs real
    context-aware contract-first extraction per chunk (bounded repair,
    fail closed, append-only ``ingestion_chunk_runs`` history) instead of
    the fake chunk executor. When unset, ``extract`` keeps the C1-T4 fake
    behavior. ``extraction_schema`` pins validation to the canonical
    Chronicle staged-bundle schema: ``None`` binds it automatically and
    a supplied dict must equal it exactly (anything else fails closed);
    ``allowed_predicates`` tightens validation when supplied; ``document_meta``
    supplies document-level extraction metadata (e.g. a verified
    normalized year) over the database title.
    """

    def __init__(
        self,
        database_url: str,
        *,
        worker: str,
        executor: StageExecutor | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        stop: threading.Event | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        revision_source: Callable[[uuid.UUID], tuple[str, str] | None] | None = None,
        segmentation_config: SegmentationConfig | None = None,
        chunk_model: Any | None = None,
        extraction_config: extraction.ExtractionConfig | None = None,
        extraction_schema: dict[str, Any] | None = None,
        allowed_predicates: list[str] | None = None,
        document_meta: dict[str, Any] | None = None,
    ) -> None:
        if not isinstance(worker, str) or not worker:
            raise PersistenceError("worker must be a non-empty string")
        if lease_seconds < 1:
            raise PersistenceError("lease_seconds must be a positive integer")
        if chunk_model is not None and (
            not callable(getattr(chunk_model, "complete", None))
            or not isinstance(getattr(chunk_model, "name", None), str)
        ):
            raise PersistenceError(
                "chunk_model must expose complete(prompt)->str and a string name"
            )
        self.database_url = database_url
        self.worker = worker
        self.executor = executor or StageExecutor()
        self.lease_seconds = lease_seconds
        self.stop = stop or threading.Event()
        self.on_event = on_event
        self.revision_source = revision_source
        self.segmentation_config = segmentation_config or SegmentationConfig()
        self.chunk_model = chunk_model
        self.extraction_config = extraction_config or extraction.ExtractionConfig()
        self.extraction_schema = extraction_schema
        self.allowed_predicates = allowed_predicates
        self.document_meta = dict(document_meta or {})

    # -- single-transaction steps --------------------------------------

    def _read_job(self, job_id: uuid.UUID) -> tuple[str, int, int, uuid.UUID]:
        """Read (status, attempt, max_attempts, revision_id) and commit."""
        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                """
                SELECT status, attempt, max_attempts, revision_id
                FROM chronicle.ingestion_jobs WHERE job_id = %s
                """,
                (job_id,),
            ).fetchone()
            if row is None:
                raise PersistenceError(f"unknown job {job_id}")
            return row[0], int(row[1]), int(row[2]), row[3]

    def _read_stage(self, job_id: uuid.UUID, stage: str) -> str:
        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                """
                SELECT status FROM chronicle.ingestion_job_stages
                WHERE job_id = %s AND stage = %s
                """,
                (job_id, stage),
            ).fetchone()
            if row is None:
                raise PersistenceError(f"unknown stage {stage!r} for job {job_id}")
            return row[0]

    def _read_chunk(self, chunk_id: uuid.UUID) -> tuple[str, int]:
        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                """
                SELECT status, chunk_index FROM chronicle.ingestion_chunks
                WHERE chunk_id = %s
                """,
                (chunk_id,),
            ).fetchone()
            if row is None:  # pragma: no cover - defensive; chunk was just ensured
                raise PersistenceError(f"unknown chunk {chunk_id}")
            return row[0], int(row[1])

    def _heartbeat(self, job_id: uuid.UUID) -> None:
        """Renew the lease in one committed transaction; `LeaseLost` on takeover."""
        with psycopg.connect(self.database_url) as conn:
            control_plane.heartbeat_job_strict(
                conn, job_id=job_id, worker=self.worker,
                lease_seconds=self.lease_seconds,
            )

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self.on_event is not None:
            self.on_event(event, payload)

    def check_halt(self, job_id: uuid.UUID) -> str | None:
        """Return 'cancelled'/'stopped' when the runner must halt, else None.

        A single committed read: cancellation (or any externally imposed
        non-running status) is visible here even while a previous executor
        step is still winding down, because no transaction is held open.
        """
        if self.stop.is_set():
            return "stopped"
        status = self._read_job(job_id)[0]
        if status == "cancelled":
            return "cancelled"
        if status != "running":
            # Externally parked (failed/needs_review/completed by another
            # actor): stop writing rather than overwriting that decision.
            return "stopped"
        return None

    def ensure_fake_topology(
        self, job_id: uuid.UUID
    ) -> tuple[uuid.UUID, list[uuid.UUID]]:
        """Ensure one section + N chunks, each step committed; idempotent.

        Reuses existing ``(job, index)`` rows on re-entry after a crash, so
        resume never duplicates sections/chunks or loses their checkpoints.
        Topology inserts are lease-fenced to this runner's worker.
        """
        with psycopg.connect(self.database_url) as conn:
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
                section_id = None
                with conn.transaction():
                    control_plane.require_job_lease(conn, job_id=job_id, worker=self.worker)
                    try:
                        section_id = control_plane.create_section(
                            conn, job_id=job_id, section_index=0,
                            label="fake-section", source_start=0,
                            source_end=FAKE_CHUNKS_PER_JOB * 512,
                        )
                    except PersistenceConflict:
                        # A concurrent worker won the insert race; fall
                        # through to the committed re-read below.
                        pass
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
                            f"fake section vanished for job {job_id}"
                        )
                    section_id = row[0]
        chunk_ids: list[uuid.UUID] = []
        for index in range(FAKE_CHUNKS_PER_JOB):
            with psycopg.connect(self.database_url) as conn:
                row = conn.execute(
                    """
                    SELECT chunk_id FROM chronicle.ingestion_chunks
                    WHERE job_id = %s AND chunk_index = %s
                    """,
                    (job_id, index),
                ).fetchone()
                if row is not None:
                    chunk_ids.append(row[0])
                    continue
                with conn.transaction():
                    control_plane.require_job_lease(conn, job_id=job_id, worker=self.worker)
                    chunk_ids.append(
                        control_plane.record_chunk(
                            conn, job_id=job_id, section_id=section_id,
                            chunk_index=index, source_start=index * 512,
                            source_end=(index + 1) * 512,
                            source_sha256=_fake_sha(str(job_id), "source", str(index)),
                            content_sha256=_fake_sha(str(job_id), "content", str(index)),
                        )
                    )
        return section_id, chunk_ids

    # -- C1-T5 real structure/segment path -------------------------------

    def _load_real_plan(
        self, job_id: uuid.UUID
    ) -> tuple[str, str, segmentation.SegmentationResult] | None:
        """Resolve the deterministic segmentation plan for a job, if any.

        Returns ``(text, source_sha256, plan)`` when ``revision_source``
        supplies the revision text, else ``None`` (fake path). The
        callback's hash is verified against the job's immutable revision
        row before the plan is accepted: a mismatched source fails closed
        instead of segmenting bytes the revision does not own. Pure
        compute apart from short verification reads: no transaction is
        held open across the source callback.
        """
        if self.revision_source is None:
            return None
        # No connection is open across this call: a slow source read holds
        # no row lock and hides no lease expiry.
        loaded = self.revision_source(job_id)
        if loaded is None:
            return None
        text, source_sha256 = loaded
        _, _, _, revision_id = self._read_job(job_id)
        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                """
                SELECT source_sha256 FROM chronicle.document_revisions
                WHERE revision_id = %s
                """,
                (revision_id,),
            ).fetchone()
            if row is None:
                raise PersistenceError(f"unknown revision {revision_id}")
            if row[0] != source_sha256:
                raise PersistenceError(
                    f"revision source for job {job_id} failed verification: "
                    "callback hash does not match the immutable revision row "
                    "(refusing to segment bytes the revision does not own)"
                )
        plan = segmentation.segment_revision(
            text, source_sha256, self.segmentation_config
        )
        return text, source_sha256, plan

    def _read_revision_no(self, revision_id: uuid.UUID) -> int:
        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                """
                SELECT revision_no FROM chronicle.document_revisions
                WHERE revision_id = %s
                """,
                (revision_id,),
            ).fetchone()
            if row is None:
                raise PersistenceError(f"unknown revision {revision_id}")
            return int(row[0])

    def _read_chunk_ids(self, job_id: uuid.UUID) -> list[uuid.UUID]:
        """Return persisted chunk ids in plan order, or [] when none exist."""
        with psycopg.connect(self.database_url) as conn:
            rows = conn.execute(
                """
                SELECT chunk_id FROM chronicle.ingestion_chunks
                WHERE job_id = %s ORDER BY chunk_index
                """,
                (job_id,),
            ).fetchall()
            return [row[0] for row in rows]

    def _execute_real_stage(
        self,
        job_id: uuid.UUID,
        stage: str,
        text: str,
        source_sha256: str,
        plan: segmentation.SegmentationResult,
    ) -> str:
        """Execute one real structure/segment stage; returns 'ok' or a halt.

        Raises :class:`LeaseLost` when this worker no longer holds the
        lease; the caller maps it to the 'lease_lost' outcome. Every
        durable step commits before the next begins; re-entry after a
        crash reuses the persisted sections/chunks instead of duplicating
        them, and completed stages are skipped by the caller.
        """
        with psycopg.connect(self.database_url) as conn:
            control_plane.advance_stage_fenced(
                conn, job_id=job_id, stage=stage,
                status="running", worker=self.worker,
            )
        self._heartbeat(job_id)
        if stage == "structure":
            # No connection is open across segmentation: pure compute.
            with psycopg.connect(self.database_url) as conn:
                with conn.transaction():
                    control_plane.require_job_lease(
                        conn, job_id=job_id, worker=self.worker
                    )
                    segmentation.ensure_sections(conn, job_id=job_id, plan=plan)
            halt = self.check_halt(job_id)
            if halt is not None:
                return halt
            with psycopg.connect(self.database_url) as conn:
                control_plane.write_stage_checkpoint_fenced(
                    conn, job_id=job_id, stage=stage,
                    worker=self.worker,
                    checkpoint={
                        "segmentation_version": segmentation.SEGMENTATION_VERSION,
                        "structure_version": segmentation.STRUCTURE_VERSION,
                        "model_version": segmentation.MODEL_VERSION,
                        "prompt_version": segmentation.PROMPT_VERSION,
                        "offset_unit": segmentation.OFFSET_UNIT,
                        "config": self.segmentation_config.to_dict(),
                        "source_sha256": source_sha256,
                        "structure": plan.manifest["structure"],
                        "section_count": len(plan.sections),
                        "plan_sha256": plan.manifest["plan_sha256"],
                    },
                )
                control_plane.advance_stage_fenced(
                    conn, job_id=job_id, stage=stage,
                    status="completed", worker=self.worker,
                )
            self._emit("stage_completed", {"stage": stage})
            return "ok"
        # stage == "segment": persist chunks, forward context state, gate budgets.
        with psycopg.connect(self.database_url) as conn:
            with conn.transaction():
                control_plane.require_job_lease(
                    conn, job_id=job_id, worker=self.worker
                )
                section_ids = segmentation.ensure_sections(
                    conn, job_id=job_id, plan=plan
                )
                chunk_ids = segmentation.ensure_chunks(
                    conn, job_id=job_id, plan=plan,
                    source_sha256=source_sha256,
                    section_ids=section_ids,
                )
        halt = self.check_halt(job_id)
        if halt is not None:
            return halt
        # Pure compute between connections: context chain + budget gates.
        pairs = segmentation.context_chain(plan, text, self.segmentation_config)
        halt = self.check_halt(job_id)
        if halt is not None:
            return halt
        _, _, _, revision_id = self._read_job(job_id)
        revision_no = self._read_revision_no(revision_id)
        section_lookup = self._read_section_lookup(job_id)
        for chunk, chunk_id, pair in zip(plan.chunks, chunk_ids, pairs):
            locator = segmentation.chunk_locator(
                job_id=job_id,
                revision_id=revision_id,
                revision_no=revision_no,
                source_sha256=source_sha256,
                chunk=chunk,
                section_id=section_lookup.get(chunk.section_index),
            )
            checkpoint = segmentation.chunk_checkpoint(
                locator=locator,
                context={"input": pair["input"], "output": pair["output"]},
                manifest_ref={
                    "plan_sha256": plan.manifest["plan_sha256"],
                    "boundary_head": chunk.boundary_head,
                    "boundary_tail": chunk.boundary_tail,
                },
            )
            with psycopg.connect(self.database_url) as conn:
                control_plane.write_chunk_checkpoint_fenced(
                    conn, job_id=job_id, chunk_id=chunk_id,
                    worker=self.worker, checkpoint=checkpoint,
                )
        with psycopg.connect(self.database_url) as conn:
            control_plane.write_stage_checkpoint_fenced(
                conn, job_id=job_id, stage=stage,
                worker=self.worker,
                checkpoint={
                    "segmentation_version": segmentation.SEGMENTATION_VERSION,
                    "context_version": segmentation.CONTEXT_VERSION,
                    "model_version": segmentation.MODEL_VERSION,
                    "prompt_version": segmentation.PROMPT_VERSION,
                    "offset_unit": segmentation.OFFSET_UNIT,
                    "config": self.segmentation_config.to_dict(),
                    "source_sha256": source_sha256,
                    "plan_sha256": plan.manifest["plan_sha256"],
                    "chunk_count": len(plan.chunks),
                    "budgets_fit": all(
                        p["output"]["budget"]["fits"] for p in pairs
                    ),
                },
            )
            control_plane.advance_stage_fenced(
                conn, job_id=job_id, stage=stage,
                status="completed", worker=self.worker,
            )
        self._emit("stage_completed", {"stage": stage})
        return "ok"

    def _read_section_lookup(self, job_id: uuid.UUID) -> dict[int, uuid.UUID]:
        with psycopg.connect(self.database_url) as conn:
            rows = conn.execute(
                """
                SELECT section_index, section_id
                FROM chronicle.ingestion_sections
                WHERE job_id = %s ORDER BY section_index
                """,
                (job_id,),
            ).fetchall()
            return {int(row[0]): row[1] for row in rows}

    def _read_section_meta(self, job_id: uuid.UUID) -> dict[int, dict[str, Any]]:
        """Return persisted section metadata keyed by section index."""
        with psycopg.connect(self.database_url) as conn:
            rows = conn.execute(
                """
                SELECT section_index, label, kind
                FROM chronicle.ingestion_sections
                WHERE job_id = %s ORDER BY section_index
                """,
                (job_id,),
            ).fetchall()
            return {
                int(row[0]): {"label": row[1], "kind": row[2], "section_index": int(row[0])}
                for row in rows
            }

    def _read_document_meta(self, job_id: uuid.UUID) -> dict[str, Any]:
        """Return document-level extraction metadata for a job's revision."""
        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                """
                SELECT d.title, r.revision_id, r.revision_no
                FROM chronicle.ingestion_jobs j
                JOIN chronicle.document_revisions r ON r.revision_id = j.revision_id
                JOIN chronicle.documents d ON d.document_id = r.document_id
                WHERE j.job_id = %s
                """,
                (job_id,),
            ).fetchone()
            if row is None:
                raise PersistenceError(f"unknown job {job_id}")
            meta: dict[str, Any] = {"title": row[0]}
            meta.update(self.document_meta)
            return {
                "document": meta,
                "revision_id": row[1],
                "revision_no": int(row[2]),
            }

    def _read_extract_chunks(
        self, job_id: uuid.UUID
    ) -> list[tuple[uuid.UUID, int, str, dict[str, Any]]]:
        """Return ``(chunk_id, chunk_index, status, checkpoint)`` in plan order."""
        with psycopg.connect(self.database_url) as conn:
            rows = conn.execute(
                """
                SELECT chunk_id, chunk_index, status, checkpoint
                FROM chronicle.ingestion_chunks
                WHERE job_id = %s ORDER BY chunk_index
                """,
                (job_id,),
            ).fetchall()
            return [
                (row[0], int(row[1]), row[2], row[3] if row[3] is not None else {})
                for row in rows
            ]

    # -- C1-T6 real context-aware extraction path ------------------------

    def _adopt_accepted_run(
        self,
        job_id: uuid.UUID,
        chunk_id: uuid.UUID,
        *,
        locator: dict[str, Any],
        context_output: dict[str, Any] | None,
    ) -> bool:
        """Adopt an already-accepted run without calling the model.

        Closes the crash window between the accepted ``ingestion_chunk_runs``
        commit and the accepted-layer/status commit: when a previous
        execution recorded an accepted run but the chunk never reached
        ``completed`` (worker exit between those commits), resume adopts
        the newest accepted run instead of invoking the model again, so a
        successful chunk is never duplicated on ordinary resume. The
        adoption (checkpoint merge + ``completed``) commits atomically
        under the lease. Returns True when a run was adopted.
        """
        with psycopg.connect(self.database_url) as conn:
            rows = conn.execute(
                """
                SELECT attempt, status, checkpoint
                FROM chronicle.ingestion_chunk_runs
                WHERE chunk_id = %s ORDER BY attempt
                """,
                (chunk_id,),
            ).fetchall()
        adopted: tuple[int, dict[str, Any]] | None = None
        for attempt, status, checkpoint in rows:
            checkpoint = checkpoint if isinstance(checkpoint, dict) else {}
            if status == "completed" and checkpoint.get("accepted") is True:
                candidate = checkpoint.get("candidate")
                if isinstance(candidate, dict):
                    adopted = (int(attempt), candidate)
        if adopted is None:
            return False
        run_attempt, candidate = adopted
        accepted = extraction.build_accepted_checkpoint(
            candidate=candidate,
            run_attempt=run_attempt,
            locator=locator,
            context_output=context_output,
        )
        with psycopg.connect(self.database_url) as conn:
            with conn.transaction():
                control_plane.require_job_lease(
                    conn, job_id=job_id, worker=self.worker
                )
                current = conn.execute(
                    """
                    SELECT checkpoint FROM chronicle.ingestion_chunks
                    WHERE chunk_id = %s
                    """,
                    (chunk_id,),
                ).fetchone()
                if current is None:
                    raise PersistenceError(f"unknown chunk {chunk_id}")
                merged = dict(current[0] or {})
                merged["extraction"] = accepted
                control_plane.write_chunk_checkpoint(
                    conn, chunk_id=chunk_id, checkpoint=merged
                )
                control_plane.set_chunk_status(
                    conn, chunk_id=chunk_id, status="completed"
                )
        self._emit(
            "chunk_reconciled",
            {"chunk_id": str(chunk_id), "run_attempt": run_attempt},
        )
        return True

    def _execute_real_extract(self, job_id: uuid.UUID) -> str:
        """Execute the ``extract`` stage with real chunk extraction.

        Returns 'ok'/'failed'/'needs_review'/'cancelled'/'stopped'.
        Raises :class:`LeaseLost` when this worker no longer holds the
        lease. Every model attempt appends an ``ingestion_chunk_runs``
        row (never overwrites); completed chunks are never re-run, and a
        chunk with an already-accepted run is adopted without a new
        model call, so ordinary resume (including a crash between the
        accepted-run commit and the status commit) never duplicates a
        successful chunk. A chunk whose model output cannot be grounded
        fails closed (bounded Studio retry, then ``needs_review``);
        nothing is silently coerced into a valid-looking candidate.
        """
        if self.revision_source is None:
            raise PersistenceError(
                "real extraction requires revision_source (refusing to run "
                "the model against unknown bytes)"
            )
        # Canonical contract binding (fail closed): None binds the
        # canonical staged-bundle schema; any non-canonical dict is
        # rejected so permissive schemas cannot accept malformed
        # candidates.
        schema = extraction.require_canonical_schema(self.extraction_schema)
        loaded = self._load_real_plan(job_id)
        if loaded is None:
            raise PersistenceError(
                "real extraction requires revision_source (refusing to run "
                "the model against unknown bytes)"
            )
        text, source_sha256, plan = loaded
        self._heartbeat(job_id)
        pairs = segmentation.context_chain(plan, text, self.segmentation_config)
        by_index = {c.chunk_index: c for c in plan.chunks}
        section_meta = self._read_section_meta(job_id)
        doc_info = self._read_document_meta(job_id)
        document = doc_info["document"]
        rows = self._read_extract_chunks(job_id)
        if [index for _, index, _, _ in rows] != [c.chunk_index for c in plan.chunks]:
            raise PersistenceError(
                f"job {job_id} persists chunks "
                f"{[index for _, index, _, _ in rows]} but the plan needs "
                f"{[c.chunk_index for c in plan.chunks]}; refusing to extract "
                "on a stale chunk set (run the segment stage first)"
            )
        section_lookup = self._read_section_lookup(job_id)
        for chunk_id, chunk_index, status, _checkpoint in rows:
            halt = self.check_halt(job_id)
            if halt is not None:
                return halt
            if status == "completed":
                continue  # checkpoint skip: never re-run succeeded work
            if status not in ("pending", "running", "failed", "needs_review"):
                raise PersistenceError(
                    f"chunk {chunk_id} has unexpected status {status!r}"
                )
            chunk = by_index[chunk_index]
            pair = pairs[chunk_index] if chunk_index < len(pairs) else pairs[-1]
            locator = segmentation.chunk_locator(
                job_id=job_id,
                revision_id=doc_info["revision_id"],
                revision_no=doc_info["revision_no"],
                source_sha256=source_sha256,
                chunk=chunk,
                section_id=section_lookup.get(chunk.section_index),
            )
            # Crash-window reconciliation first: an accepted run whose
            # status commit never landed is adopted with zero model
            # calls instead of being extracted again.
            if self._adopt_accepted_run(
                job_id, chunk_id,
                locator=locator, context_output=pair["output"],
            ):
                continue
            with psycopg.connect(self.database_url) as conn:
                control_plane.set_chunk_status_fenced(
                    conn, job_id=job_id, chunk_id=chunk_id,
                    status="running", worker=self.worker,
                )
            self._heartbeat(job_id)
            # No connection is open across model calls: a slow model
            # holds no row lock and hides no lease expiry.
            chunk_text = text[chunk.source_start : chunk.source_end]
            section = section_meta.get(
                chunk.section_index,
                {"label": f"section-{chunk.section_index}",
                 "kind": "unknown", "section_index": chunk.section_index},
            )
            try:
                request = extraction.build_chunk_request(
                    chunk_text=chunk_text,
                    section=section,
                    document=document,
                    context_input=pair["input"],
                    boundary_head=chunk.boundary_head,
                    boundary_tail=chunk.boundary_tail,
                    locator=locator,
                    config=self.extraction_config,
                )
                result = extraction.extract_chunk(
                    self.chunk_model,
                    request,
                    chunk_text=chunk_text,
                    context_input=pair["input"],
                    section_label=section["label"],
                    document=document,
                    schema=schema,
                    allowed_predicates=self.allowed_predicates,
                    config=self.extraction_config,
                )
                run_checkpoint = extraction.build_chunk_run(
                    request=request,
                    provider_name=self.chunk_model.name,
                    result=result,
                    context_output=pair["output"],
                )
            except Exception as exc:
                with psycopg.connect(self.database_url) as conn:
                    control_plane.record_chunk_run_fenced(
                        conn, job_id=job_id, chunk_id=chunk_id,
                        status="failed", worker=self.worker,
                        checkpoint={
                            "extraction_version": extraction.EXTRACTION_VERSION,
                            "contract_version": extraction.CONTRACT_VERSION,
                            "accepted": False,
                            "attempts": [],
                            "attempt_count": 0,
                            "authoritative": False,
                            "authority_note": extraction.NON_AUTHORITATIVE_NOTE,
                        },
                        error=f"extraction harness failed: {exc}",
                    )
                    control_plane.set_chunk_status_fenced(
                        conn, job_id=job_id, chunk_id=chunk_id,
                        status="failed", worker=self.worker,
                    )
                self._emit("chunk_failed", {"chunk_id": str(chunk_id), "error": str(exc)})
                return self._failed_extract_outcome(job_id, chunk_id)
            # One run row per model attempt: history is append-only, so a
            # correction never overwrites the attempt it repairs.
            attempts = result["attempts"]
            for position, attempt in enumerate(attempts):
                last = position == len(attempts) - 1
                row_status = (
                    "completed" if (last and result["accepted"]) else "failed"
                )
                with psycopg.connect(self.database_url) as conn:
                    _, run_attempt = control_plane.record_chunk_run_fenced(
                        conn, job_id=job_id, chunk_id=chunk_id,
                        status=row_status, worker=self.worker,
                        checkpoint={
                            **run_checkpoint,
                            "attempts": attempts[: position + 1],
                            "attempt_count": position + 1,
                        },
                        error=None if row_status == "completed" else (
                            result.get("error")
                            if last
                            else "superseded by bounded correction re-ask"
                        ),
                    )
            halt = self.check_halt(job_id)
            if halt is not None:
                return halt
            if result["accepted"]:
                accepted = extraction.build_accepted_checkpoint(
                    candidate=result["candidate"],
                    run_attempt=run_attempt,
                    locator=locator,
                    context_output=pair["output"],
                )
                with psycopg.connect(self.database_url) as conn:
                    with conn.transaction():
                        control_plane.require_job_lease(
                            conn, job_id=job_id, worker=self.worker
                        )
                        current = conn.execute(
                            """
                            SELECT checkpoint FROM chronicle.ingestion_chunks
                            WHERE chunk_id = %s
                            """,
                            (chunk_id,),
                        ).fetchone()
                        merged = dict(current[0] or {})
                        merged["extraction"] = accepted
                        control_plane.write_chunk_checkpoint(
                            conn, chunk_id=chunk_id, checkpoint=merged
                        )
                        control_plane.set_chunk_status(
                            conn, chunk_id=chunk_id, status="completed"
                        )
                self._emit("chunk_completed", {"chunk_id": str(chunk_id)})
                continue
            with psycopg.connect(self.database_url) as conn:
                control_plane.set_chunk_status_fenced(
                    conn, job_id=job_id, chunk_id=chunk_id,
                    status="failed", worker=self.worker,
                )
            self._emit(
                "chunk_failed",
                {"chunk_id": str(chunk_id), "error": result.get("error")},
            )
            return self._failed_extract_outcome(job_id, chunk_id)
        return "ok"

    def _failed_extract_outcome(self, job_id: uuid.UUID, chunk_id: uuid.UUID) -> str:
        """Map a failed chunk to 'failed' (bounded retry) or 'needs_review'."""
        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                """
                SELECT attempt, max_attempts
                FROM chronicle.ingestion_chunks WHERE chunk_id = %s
                """,
                (chunk_id,),
            ).fetchone()
        if int(row[0]) >= int(row[1]):
            return "needs_review"
        return "failed"

    # -- C1-T7 real source-assembly path --------------------------------

    def _read_assemble_inputs(
        self, job_id: uuid.UUID
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        """Read accepted per-chunk extraction outputs for assembly.

        Returns ``(chunks, document, revision)`` for
        :func:`assembly.assemble_revision`. Every chunk must be
        ``completed`` with an accepted extraction layer; anything else
        fails closed instead of assembling a partial bundle.
        """
        with psycopg.connect(self.database_url) as conn:
            meta = conn.execute(
                """
                SELECT d.title, r.revision_id, r.revision_no, r.source_sha256
                FROM chronicle.ingestion_jobs j
                JOIN chronicle.document_revisions r ON r.revision_id = j.revision_id
                JOIN chronicle.documents d ON d.document_id = r.document_id
                WHERE j.job_id = %s
                """,
                (job_id,),
            ).fetchone()
            if meta is None:
                raise PersistenceError(f"unknown job {job_id}")
            rows = conn.execute(
                """
                SELECT chunk_id, chunk_index, status, checkpoint
                FROM chronicle.ingestion_chunks
                WHERE job_id = %s ORDER BY chunk_index
                """,
                (job_id,),
            ).fetchall()
        if not rows:
            raise PersistenceError(
                f"job {job_id} persists no chunks; refusing to assemble "
                "a source bundle from nothing"
            )
        chunks: list[dict[str, Any]] = []
        for chunk_id, chunk_index, status, checkpoint in rows:
            checkpoint = checkpoint if isinstance(checkpoint, dict) else {}
            accepted = checkpoint.get("extraction")
            if status != "completed" or not isinstance(accepted, dict):
                raise PersistenceError(
                    f"chunk {chunk_id} (index {chunk_index}) has no accepted "
                    "extraction output; refusing to assemble a partial bundle"
                )
            if accepted.get("accepted") is not True or not isinstance(
                accepted.get("candidate"), dict
            ):
                raise PersistenceError(
                    f"chunk {chunk_id} (index {chunk_index}) has no accepted "
                    "extraction candidate; refusing to assemble"
                )
            run_attempt = accepted.get("produced_by_run_attempt")
            if not isinstance(run_attempt, int) or run_attempt < 1:
                raise PersistenceError(
                    f"chunk {chunk_id} accepted output names no producing run"
                )
            with psycopg.connect(self.database_url) as conn:
                run = conn.execute(
                    """
                    SELECT checkpoint FROM chronicle.ingestion_chunk_runs
                    WHERE chunk_id = %s AND attempt = %s
                    """,
                    (chunk_id, run_attempt),
                ).fetchone()
            if run is None or not isinstance(run[0], dict):
                raise PersistenceError(
                    f"chunk {chunk_id} producing run {run_attempt} is missing"
                )
            model_version = run[0].get("model_version")
            if not isinstance(model_version, str) or not model_version:
                raise PersistenceError(
                    f"chunk {chunk_id} producing run names no model version"
                )
            chunks.append(
                {
                    "chunk_index": int(chunk_index),
                    "candidate": accepted["candidate"],
                    "locator": accepted["locator"],
                    "run_attempt": run_attempt,
                    "model_version": model_version,
                }
            )
        document = {"title": meta[0]}
        document.update(self.document_meta)
        revision = {
            "revision_id": str(meta[1]),
            "revision_no": int(meta[2]),
            "source_sha256": meta[3],
        }
        return chunks, document, revision

    def _execute_real_assemble(self, job_id: uuid.UUID) -> str:
        """Execute the ``assemble`` stage over accepted chunk outputs.

        Returns 'ok'/'failed'/'cancelled'/'stopped'. Raises
        :class:`LeaseLost` when this worker no longer holds the lease.
        The deterministic assembly artifact (bundle + within-book links
        + report) is recorded as one control-plane output; rerunning a
        completed assemble stage is a checkpoint skip, and repeating an
        identical assembly is idempotent through the output's content
        addressing.
        """
        halt = self.check_halt(job_id)
        if halt is not None:
            return halt
        self._heartbeat(job_id)
        # No connection is open across assembly: pure compute only.
        try:
            chunks, document, revision = self._read_assemble_inputs(job_id)
            artifact = assembly.assemble_revision(
                chunks=chunks, document=document, revision=revision
            )
        except PersistenceError as exc:
            with psycopg.connect(self.database_url) as conn:
                control_plane.advance_stage_fenced(
                    conn, job_id=job_id, stage=REAL_ASSEMBLE_STAGE,
                    status="failed", worker=self.worker,
                    error=f"real assembly failed closed: {exc}",
                )
                control_plane.set_job_status_fenced(
                    conn, job_id=job_id, status="failed",
                    worker=self.worker,
                    error=f"real assembly failed closed: {exc}",
                )
            self._emit("stage_failed", {"stage": REAL_ASSEMBLE_STAGE, "error": str(exc)})
            return "failed"
        halt = self.check_halt(job_id)
        if halt is not None:
            return halt
        artifact_sha = assembly.sha256_json(artifact)
        with psycopg.connect(self.database_url) as conn:
            control_plane.record_output_fenced(
                conn, job_id=job_id, revision_id=uuid.UUID(revision["revision_id"]),
                worker=self.worker, artifact_type=assembly.ARTIFACT_TYPE,
                artifact_sha256=artifact_sha, payload=artifact,
            )
            control_plane.write_stage_checkpoint_fenced(
                conn, job_id=job_id, stage=REAL_ASSEMBLE_STAGE,
                worker=self.worker,
                checkpoint={
                    "assembly_version": assembly.ASSEMBLY_VERSION,
                    "contract_version": assembly.CONTRACT_VERSION,
                    "artifact_type": assembly.ARTIFACT_TYPE,
                    "artifact_sha256": artifact_sha,
                    "bundle_sha256": artifact["report"]["bundle_sha256"],
                    "counts": artifact["report"]["counts"],
                    "authoritative": False,
                    "authority_note": assembly.NON_AUTHORITATIVE_NOTE,
                },
            )
            control_plane.advance_stage_fenced(
                conn, job_id=job_id, stage=REAL_ASSEMBLE_STAGE,
                status="completed", worker=self.worker,
            )
        self._emit("stage_completed", {"stage": REAL_ASSEMBLE_STAGE})
        return "ok"

    # -- chunk + stage execution ----------------------------------------

    def execute_chunks(self, job_id: uuid.UUID, chunk_ids: list[uuid.UUID]) -> str:
        """Execute every chunk; returns 'ok'/'failed'/'needs_review'/'cancelled'/'stopped'.

        Raises :class:`LeaseLost` when this worker no longer holds the
        lease; the caller maps it to the 'lease_lost' outcome.
        """
        for chunk_id in chunk_ids:
            halt = self.check_halt(job_id)
            if halt is not None:
                return halt
            status, chunk_index = self._read_chunk(chunk_id)
            if status == "completed":
                continue  # checkpoint skip: never re-run succeeded work
            if status not in ("pending", "running", "failed", "needs_review"):
                raise PersistenceError(
                    f"chunk {chunk_id} has unexpected status {status!r}"
                )
            with psycopg.connect(self.database_url) as conn:
                control_plane.set_chunk_status_fenced(
                    conn, job_id=job_id, chunk_id=chunk_id,
                    status="running", worker=self.worker,
                )
            self._heartbeat(job_id)
            # No connection is open across this call: a hung chunk cannot
            # hold a row lock or hide its lease expiry.
            try:
                checkpoint = self.executor.execute_chunk(chunk_index, job_id)
            except StageExecutionError as exc:
                with psycopg.connect(self.database_url) as conn:
                    control_plane.record_chunk_run_fenced(
                        conn, job_id=job_id, chunk_id=chunk_id,
                        status="failed", worker=self.worker,
                        checkpoint={"worker_version": WORKER_VERSION},
                        error=str(exc),
                    )
                    control_plane.set_chunk_status_fenced(
                        conn, job_id=job_id, chunk_id=chunk_id,
                        status="failed", worker=self.worker,
                    )
                self._emit("chunk_failed", {"chunk_id": str(chunk_id), "error": str(exc)})
                # Bounded retry: further attempts arrive through the Studio
                # retry operation, which appends a new ChunkRun row.
                with psycopg.connect(self.database_url) as conn:
                    row = conn.execute(
                        """
                        SELECT attempt, max_attempts
                        FROM chronicle.ingestion_chunks WHERE chunk_id = %s
                        """,
                        (chunk_id,),
                    ).fetchone()
                if int(row[0]) >= int(row[1]):
                    return "needs_review"
                return "failed"
            with psycopg.connect(self.database_url) as conn:
                control_plane.record_chunk_run_fenced(
                    conn, job_id=job_id, chunk_id=chunk_id,
                    status="completed", worker=self.worker,
                    checkpoint=checkpoint,
                )
                control_plane.set_chunk_status_fenced(
                    conn, job_id=job_id, chunk_id=chunk_id,
                    status="completed", worker=self.worker,
                )
            self._emit("chunk_completed", {"chunk_id": str(chunk_id)})
        return "ok"

    def execute_job(self, job_id: uuid.UUID) -> str:
        """Execute one claimed job; returns the outcome string.

        Outcomes: 'completed', 'failed', 'needs_review', 'cancelled',
        'stopped', 'lease_lost'. Every durable step commits before the
        next begins; losing the lease halts with 'lease_lost' without
        writing further state.
        """
        try:
            return self._execute_job(job_id)
        except LeaseLost as exc:
            self._emit("lease_lost", {"job_id": str(job_id), "error": str(exc)})
            return "lease_lost"

    def _execute_job(self, job_id: uuid.UUID) -> str:
        halt = self.check_halt(job_id)
        if halt is not None:
            return halt
        real_unset: Any = object()
        real: Any = real_unset
        for stage in control_plane.STAGE_NAMES:
            halt = self.check_halt(job_id)
            if halt is not None:
                return halt
            stage_status = self._read_stage(job_id, stage)
            if stage_status in ("completed", "skipped"):
                continue  # checkpoint skip: never re-run succeeded work
            if stage_status in ("pending", "failed", "needs_review"):
                with psycopg.connect(self.database_url) as conn:
                    control_plane.advance_stage_fenced(
                        conn, job_id=job_id, stage=stage,
                        status="running", worker=self.worker,
                    )
            # A `running` stage is re-entry after a crash: checkpointed
            # state is authoritative, so execution resumes in place.
            self._heartbeat(job_id)
            if stage in REAL_SEGMENT_STAGES:
                if real is real_unset:
                    try:
                        real = self._load_real_plan(job_id)
                    except Exception as exc:
                        with psycopg.connect(self.database_url) as conn:
                            control_plane.advance_stage_fenced(
                                conn, job_id=job_id, stage=stage,
                                status="failed", worker=self.worker,
                                error=f"real segmentation failed: {exc}",
                            )
                            control_plane.set_job_status_fenced(
                                conn, job_id=job_id, status="failed",
                                worker=self.worker,
                                error=f"real segmentation failed: {exc}",
                            )
                        self._emit("stage_failed", {"stage": stage, "error": str(exc)})
                        return "failed"
                if real is not None:
                    text, source_sha256, plan = real
                    try:
                        outcome = self._execute_real_stage(
                            job_id, stage, text, source_sha256, plan
                        )
                    except LeaseLost:
                        raise
                    except Exception as exc:
                        with psycopg.connect(self.database_url) as conn:
                            control_plane.advance_stage_fenced(
                                conn, job_id=job_id, stage=stage,
                                status="failed", worker=self.worker,
                                error=f"real segmentation failed: {exc}",
                            )
                            control_plane.set_job_status_fenced(
                                conn, job_id=job_id, status="failed",
                                worker=self.worker,
                                error=f"real segmentation failed: {exc}",
                            )
                        self._emit("stage_failed", {"stage": stage, "error": str(exc)})
                        return "failed"
                    if outcome != "ok":
                        return outcome
                    continue
            if stage == CHUNK_BEARING_STAGE:
                if self.chunk_model is not None:
                    try:
                        outcome = self._execute_real_extract(job_id)
                    except LeaseLost:
                        raise
                    except Exception as exc:
                        with psycopg.connect(self.database_url) as conn:
                            control_plane.advance_stage_fenced(
                                conn, job_id=job_id, stage=stage,
                                status="failed", worker=self.worker,
                                error=f"real extraction failed: {exc}",
                            )
                            control_plane.set_job_status_fenced(
                                conn, job_id=job_id, status="failed",
                                worker=self.worker,
                                error=f"real extraction failed: {exc}",
                            )
                        self._emit("stage_failed", {"stage": stage, "error": str(exc)})
                        return "failed"
                    if outcome == "ok":
                        with psycopg.connect(self.database_url) as conn:
                            control_plane.advance_stage_fenced(
                                conn, job_id=job_id, stage=stage,
                                status="completed", worker=self.worker,
                            )
                        self._emit("stage_completed", {"stage": stage})
                        continue
                    if outcome == "failed":
                        with psycopg.connect(self.database_url) as conn:
                            control_plane.advance_stage_fenced(
                                conn, job_id=job_id, stage=stage, status="failed",
                                worker=self.worker,
                                error="chunk extraction failed closed (bounded retry via Studio)",
                            )
                            control_plane.set_job_status_fenced(
                                conn, job_id=job_id, status="failed",
                                worker=self.worker,
                                error="chunk extraction failed closed (bounded retry via Studio)",
                            )
                        return "failed"
                    if outcome == "needs_review":
                        with psycopg.connect(self.database_url) as conn:
                            control_plane.advance_stage_fenced(
                                conn, job_id=job_id, stage=stage,
                                status="needs_review", worker=self.worker,
                                error="chunk attempts exhausted; awaiting review",
                            )
                            control_plane.open_review_item(
                                conn, job_id=job_id, kind="chunk_failure",
                                payload={"stage": stage, "worker": self.worker},
                            )
                            control_plane.set_job_status_fenced(
                                conn, job_id=job_id, status="needs_review",
                                worker=self.worker,
                                error="chunk attempts exhausted; awaiting review",
                            )
                        return "needs_review"
                    return outcome  # cancelled / stopped: checkpoints stay as written
                chunk_ids = self._read_chunk_ids(job_id)
                if not chunk_ids:
                    _, chunk_ids = self.ensure_fake_topology(job_id)
                outcome = self.execute_chunks(job_id, chunk_ids)
                if outcome == "ok":
                    with psycopg.connect(self.database_url) as conn:
                        control_plane.advance_stage_fenced(
                            conn, job_id=job_id, stage=stage,
                            status="completed", worker=self.worker,
                        )
                    self._emit("stage_completed", {"stage": stage})
                elif outcome == "failed":
                    with psycopg.connect(self.database_url) as conn:
                        control_plane.advance_stage_fenced(
                            conn, job_id=job_id, stage=stage, status="failed",
                            worker=self.worker,
                            error="fake chunk fault (bounded retry via Studio)",
                        )
                        control_plane.set_job_status_fenced(
                            conn, job_id=job_id, status="failed",
                            worker=self.worker,
                            error="fake chunk fault (bounded retry via Studio)",
                        )
                    return "failed"
                elif outcome == "needs_review":
                    with psycopg.connect(self.database_url) as conn:
                        control_plane.advance_stage_fenced(
                            conn, job_id=job_id, stage=stage,
                            status="needs_review", worker=self.worker,
                            error="chunk attempts exhausted; awaiting review",
                        )
                        control_plane.open_review_item(
                            conn, job_id=job_id, kind="chunk_failure",
                            payload={"stage": stage, "worker": self.worker},
                        )
                        control_plane.set_job_status_fenced(
                            conn, job_id=job_id, status="needs_review",
                            worker=self.worker,
                            error="chunk attempts exhausted; awaiting review",
                        )
                    return "needs_review"
                else:  # cancelled / stopped: checkpoints stay as written
                    return outcome
            if stage == REAL_ASSEMBLE_STAGE and (
                self.chunk_model is not None and self.revision_source is not None
            ):
                try:
                    outcome = self._execute_real_assemble(job_id)
                except LeaseLost:
                    raise
                except Exception as exc:
                    with psycopg.connect(self.database_url) as conn:
                        control_plane.advance_stage_fenced(
                            conn, job_id=job_id, stage=stage,
                            status="failed", worker=self.worker,
                            error=f"real assembly failed: {exc}",
                        )
                        control_plane.set_job_status_fenced(
                            conn, job_id=job_id, status="failed",
                            worker=self.worker,
                            error=f"real assembly failed: {exc}",
                        )
                    self._emit("stage_failed", {"stage": stage, "error": str(exc)})
                    return "failed"
                if outcome != "ok":
                    return outcome
                continue
            else:
                # No connection is open across this call.
                try:
                    checkpoint = self.executor.execute_stage(stage, job_id)
                except StageExecutionError as exc:
                    with psycopg.connect(self.database_url) as conn:
                        control_plane.advance_stage_fenced(
                            conn, job_id=job_id, stage=stage,
                            status="failed", worker=self.worker, error=str(exc),
                        )
                        control_plane.set_job_status_fenced(
                            conn, job_id=job_id, status="failed",
                            worker=self.worker, error=str(exc),
                        )
                    self._emit("stage_failed", {"stage": stage, "error": str(exc)})
                    return "failed"
                halt = self.check_halt(job_id)
                if halt is not None:
                    return halt
                with psycopg.connect(self.database_url) as conn:
                    control_plane.write_stage_checkpoint_fenced(
                        conn, job_id=job_id, stage=stage,
                        worker=self.worker, checkpoint=checkpoint,
                    )
                    control_plane.advance_stage_fenced(
                        conn, job_id=job_id, stage=stage,
                        status="completed", worker=self.worker,
                    )
                self._emit("stage_completed", {"stage": stage})
        halt = self.check_halt(job_id)
        if halt is not None:
            return halt
        self._heartbeat(job_id)
        _, _, _, revision_id = self._read_job(job_id)
        with psycopg.connect(self.database_url) as conn:
            control_plane.record_output_fenced(
                conn, job_id=job_id, revision_id=revision_id,
                worker=self.worker, artifact_type=FAKE_OUTPUT_TYPE,
                artifact_sha256=_fake_sha(str(job_id), FAKE_OUTPUT_TYPE),
                payload={
                    "worker_version": WORKER_VERSION,
                    "stages": list(control_plane.STAGE_NAMES),
                },
            )
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
    executor: StageExecutor | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    stop: threading.Event | None = None,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> str:
    """Compatibility entry: derive the database URL from a live connection.

    The runner itself still uses short per-step connections; `conn` is only
    used to read the connection parameters. Prefer constructing
    :class:`JobRunner` with an explicit database URL — the DSN recovered
    here never carries a password, so password-authenticated deployments
    must pass the URL explicitly.
    """
    info = conn.info
    database_url = info.dsn
    runner = JobRunner(
        database_url, worker=worker, executor=executor,
        lease_seconds=lease_seconds, stop=stop, on_event=on_event,
    )
    return runner.execute_job(job_id)


def run_once(
    database_url: str,
    *,
    worker: str,
    executor: StageExecutor | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    stop: threading.Event | None = None,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    job_id: uuid.UUID | None = None,
    revision_source: Callable[[uuid.UUID], tuple[str, str] | None] | None = None,
    segmentation_config: SegmentationConfig | None = None,
    chunk_model: Any | None = None,
    extraction_config: extraction.ExtractionConfig | None = None,
    extraction_schema: dict[str, Any] | None = None,
    allowed_predicates: list[str] | None = None,
    document_meta: dict[str, Any] | None = None,
) -> tuple[uuid.UUID, str] | None:
    """Claim one job (queued, expired-lease, or lease-less running) and run it.

    The claim commits before execution starts; execution then proceeds in
    short per-step transactions. Returns ``(job_id, outcome)`` or ``None``
    when no job is claimable. ``revision_source`` enables the C1-T5 real
    structure/segment path for jobs whose revision text it can supply;
    without it every stage uses the deterministic fake executor.
    ``chunk_model`` additionally enables the C1-T6 real extract path;
    without it the extract stage keeps the fake chunk executor.
    """
    stop = stop or threading.Event()
    with psycopg.connect(database_url) as conn:
        claimed = control_plane.claim_job(
            conn, worker=worker, lease_seconds=lease_seconds, job_id=job_id
        )
    if claimed is None:
        return None
    runner = JobRunner(
        database_url, worker=worker, executor=executor,
        lease_seconds=lease_seconds, stop=stop, on_event=on_event,
        revision_source=revision_source,
        segmentation_config=segmentation_config,
        chunk_model=chunk_model,
        extraction_config=extraction_config,
        extraction_schema=extraction_schema,
        allowed_predicates=allowed_predicates,
        document_meta=document_meta,
    )
    return claimed, runner.execute_job(claimed)


def run_forever(
    database_url: str,
    *,
    worker: str,
    executor_factory: Callable[[], StageExecutor] | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    max_jobs: int | None = None,
    stop: threading.Event | None = None,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    revision_source: Callable[[uuid.UUID], tuple[str, str] | None] | None = None,
    segmentation_config: SegmentationConfig | None = None,
    chunk_model: Any | None = None,
    extraction_config: extraction.ExtractionConfig | None = None,
    extraction_schema: dict[str, Any] | None = None,
    allowed_predicates: list[str] | None = None,
    document_meta: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Claim and execute jobs until stopped; returns an outcome tally."""
    stop = stop or threading.Event()
    tally: dict[str, int] = {}
    completed_jobs = 0
    while not stop.is_set():
        executor = executor_factory() if executor_factory else StageExecutor()
        try:
            result = run_once(
                database_url, worker=worker, executor=executor,
                lease_seconds=lease_seconds, stop=stop, on_event=on_event,
                revision_source=revision_source,
                segmentation_config=segmentation_config,
                chunk_model=chunk_model,
                extraction_config=extraction_config,
                extraction_schema=extraction_schema,
                allowed_predicates=allowed_predicates,
                document_meta=document_meta,
            )
        except PersistenceConflict:
            # Lost a claim race against a concurrent worker; keep polling.
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
        if outcome in ("stopped", "cancelled", "lease_lost"):
            # A halt concerns this worker's run loop as well as the job:
            # do not immediately re-poll into a tight loop.
            stop.wait(poll_interval)
    return tally


def install_shutdown_handlers(stop: threading.Event) -> None:
    """Wire SIGTERM/SIGINT to graceful shutdown (current checkpoints kept)."""

    def _handle(signum, _frame) -> None:
        print(f"chronicle-worker: signal {signum}; finishing current step...", flush=True)
        stop.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(signum, _handle)
        except (OSError, ValueError):
            # Non-main thread or platform without the signal: the event can
            # still be set programmatically (tests do exactly this).
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chronicle durable ingestion worker "
        "(PostgreSQL-claimed, restart-safe, no external queue)"
    )
    parser.add_argument("--database-url", default=os.environ.get("CHRONICLE_DATABASE_URL"))
    parser.add_argument(
        "--source-dir", default=None,
        help="Chronicle-owned source directory (else CHRONICLE_SOURCE_DIR). "
        "When set, structure/segment stages run the real versioned "
        "segmentation over stored revision bytes; when unset, every stage "
        "uses the deterministic fake executor.",
    )
    parser.add_argument(
        "--worker-id", default=None,
        help="lease owner identity (default: worker-<host>-<pid>-<rand>)",
    )
    parser.add_argument("--lease-seconds", type=int, default=DEFAULT_LEASE_SECONDS)
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument(
        "--max-jobs", type=int, default=None,
        help="stop after this many jobs (default: run until signalled)",
    )
    parser.add_argument(
        "--fail-stage", action="append", default=[],
        metavar="STAGE[:COUNT]",
        help="script COUNT fake failures for STAGE (repeatable; fault-injection demos only)",
    )
    return parser


def parse_fail_plan(values: list[str]) -> dict[str, int]:
    """Parse ``--fail-stage STAGE[:COUNT]`` flags into an executor fail plan."""
    plan: dict[str, int] = {}
    for raw in values:
        stage, _, count = raw.partition(":")
        stage = stage.strip()
        if stage not in control_plane.STAGE_NAMES:
            raise PersistenceError(
                f"unknown stage {stage!r}; expected one of {list(control_plane.STAGE_NAMES)}"
            )
        try:
            failures = int(count) if count else 1
        except ValueError as exc:
            raise PersistenceError(f"invalid --fail-stage {raw!r}: count must be an integer") from exc
        if failures < 1:
            raise PersistenceError(f"invalid --fail-stage {raw!r}: count must be >= 1")
        plan[stage] = plan.get(stage, 0) + failures
    return plan


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.lease_seconds < 1:
        raise PersistenceError("--lease-seconds must be a positive integer")
    if args.poll_interval <= 0:
        raise PersistenceError("--poll-interval must be positive")
    database_url = database_url_from_env(args.database_url)
    worker = args.worker_id or default_worker_id()
    fail_plan = parse_fail_plan(args.fail_stage)
    source_dir = source_dir_from_env(args.source_dir)
    revision_source = (
        build_revision_source(database_url, source_dir)
        if source_dir is not None
        else None
    )
    stop = threading.Event()
    install_shutdown_handlers(stop)
    if source_dir is not None:
        print(
            f"chronicle-worker: {worker} claiming from Chronicle PostgreSQL "
            f"(lease {args.lease_seconds}s) with real C1-T5 segmentation "
            f"from {source_dir}",
            flush=True,
        )
    else:
        print(
            f"chronicle-worker: {worker} claiming from Chronicle PostgreSQL "
            f"(lease {args.lease_seconds}s) with the deterministic fake "
            "executor (no --source-dir/CHRONICLE_SOURCE_DIR)",
            flush=True,
        )
    tally = run_forever(
        database_url, worker=worker,
        executor_factory=lambda: StageExecutor(fail_plan=dict(fail_plan)),
        lease_seconds=args.lease_seconds, poll_interval=args.poll_interval,
        max_jobs=args.max_jobs, stop=stop,
        revision_source=revision_source,
        on_event=lambda event, payload: print(
            f"chronicle-worker: {event} {payload}", flush=True
        ),
    )
    print(f"chronicle-worker: shutdown {tally}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
