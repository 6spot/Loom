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
- Every lease carries an owner identity and an expiry. Workers renew their
  own lease with ``heartbeat_job``; a crashed worker's expired lease is
  re-claimed by the next live worker, and PostgreSQL checkpoints written
  before the crash survive because they never lived in worker memory.
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
from common import PersistenceConflict, PersistenceError  # noqa: E402

try:
    import psycopg  # noqa: E402
    from psycopg.types.json import Jsonb  # noqa: E402
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

#: Fake completion artifact recorded once a job finishes every stage.
FAKE_OUTPUT_TYPE = "fake-pipeline-result"


class StageExecutionError(RuntimeError):
    """Raised by a stage executor when one deterministic fake step fails."""


class StopRequested(Exception):
    """Internal signal: graceful shutdown requested mid-job."""


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


class StageExecutor:
    """Deterministic fake stage executor.

    ``fail_plan`` maps a stage name to the number of times that stage must
    fail before it succeeds; ``fail_chunks`` maps a chunk index to the
    number of times that chunk must fail. Both counters decrement per
    attempt, so tests can script exact failure/retry sequences and
    production fakes always succeed. Real C1-T5/C1-T6 executors will
    implement :meth:`execute_stage` / :meth:`execute_chunk` instead.
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
        return {"worker_version": WORKER_VERSION, "chunk_index": chunk_index}


def _fake_sha(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def ensure_fake_topology(
    conn, *, job_id: uuid.UUID, worker: str
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Ensure the fake pipeline topology: one section + N chunks, idempotent.

    Reuses existing ``(job, index)`` rows on worker re-entry after a crash,
    so resume never duplicates sections/chunks or loses their checkpoints.
    Returns ``(section_id, chunk_ids)`` ordered by chunk index.
    """
    del worker  # topology rows carry no worker identity; runs do.
    section_id: uuid.UUID | None = None
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
            section_id = control_plane.create_section(
                conn,
                job_id=job_id,
                section_index=0,
                label="fake-section",
                source_start=0,
                source_end=FAKE_CHUNKS_PER_JOB * 512,
            )
        except PersistenceConflict:
            row = conn.execute(
                """
                SELECT section_id FROM chronicle.ingestion_sections
                WHERE job_id = %s AND section_index = 0
                """,
                (job_id,),
            ).fetchone()
            if row is None:  # pragma: no cover - defensive; conflict implies a row
                raise
            section_id = row[0]
    chunk_ids: list[uuid.UUID] = []
    for index in range(FAKE_CHUNKS_PER_JOB):
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
        chunk_ids.append(
            control_plane.record_chunk(
                conn,
                job_id=job_id,
                section_id=section_id,
                chunk_index=index,
                source_start=index * 512,
                source_end=(index + 1) * 512,
                source_sha256=_fake_sha(str(job_id), "source", str(index)),
                content_sha256=_fake_sha(str(job_id), "content", str(index)),
            )
        )
    return section_id, chunk_ids


def _job_status(conn, *, job_id: uuid.UUID) -> tuple[str, int, int]:
    row = conn.execute(
        """
        SELECT status, attempt, max_attempts
        FROM chronicle.ingestion_jobs WHERE job_id = %s
        """,
        (job_id,),
    ).fetchone()
    if row is None:
        raise PersistenceError(f"unknown job {job_id}")
    return row[0], int(row[1]), int(row[2])


def _check_cancelled_or_stop(
    conn, *, job_id: uuid.UUID, stop: threading.Event
) -> str | None:
    """Return 'cancelled'/'stopped' when the worker must halt, else None."""
    if stop.is_set():
        return "stopped"
    status, _, _ = _job_status(conn, job_id=job_id)
    if status == "cancelled":
        return "cancelled"
    return None


def _heartbeat_best_effort(conn, *, job_id: uuid.UUID, worker: str, lease_seconds: int) -> None:
    """Renew the lease; a lost race (takeover) surfaces at the next check."""
    try:
        control_plane.heartbeat_job(
            conn, job_id=job_id, worker=worker, lease_seconds=lease_seconds
        )
    except PersistenceConflict:
        # Another live worker already took over an expired lease; the next
        # cancellation/ownership read will steer this worker away.
        pass


def _chunk_max_attempts(conn, *, chunk_id: uuid.UUID) -> int:
    row = conn.execute(
        "SELECT max_attempts FROM chronicle.ingestion_chunks WHERE chunk_id = %s",
        (chunk_id,),
    ).fetchone()
    if row is None:  # pragma: no cover - defensive; chunk was just ensured
        raise PersistenceError(f"unknown chunk {chunk_id}")
    return int(row[0])


def execute_chunks(
    conn,
    *,
    job_id: uuid.UUID,
    chunk_ids: list[uuid.UUID],
    worker: str,
    executor: StageExecutor,
    lease_seconds: int,
    stop: threading.Event,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> str:
    """Execute every chunk of the chunk-bearing stage; returns an outcome.

    Outcomes: ``"ok"`` (all chunks completed), ``"needs_review"`` (a chunk
    exhausted its bounded attempts and now waits for a human gate),
    ``"cancelled"`` / ``"stopped"`` (halt requested; checkpoints preserved).
    """
    for chunk_id in chunk_ids:
        halt = _check_cancelled_or_stop(conn, job_id=job_id, stop=stop)
        if halt is not None:
            return halt
        row = conn.execute(
            "SELECT status, chunk_index FROM chronicle.ingestion_chunks WHERE chunk_id = %s",
            (chunk_id,),
        ).fetchone()
        if row is None:  # pragma: no cover - defensive; chunk was just ensured
            raise PersistenceError(f"unknown chunk {chunk_id}")
        status, chunk_index = row[0], int(row[1])
        if status == "completed":
            continue  # checkpoint skip: never re-run succeeded work
        if status not in ("pending", "running", "failed", "needs_review"):
            raise PersistenceError(f"chunk {chunk_id} has unexpected status {status!r}")
        control_plane.set_chunk_status(conn, chunk_id=chunk_id, status="running")
        _heartbeat_best_effort(conn, job_id=job_id, worker=worker, lease_seconds=lease_seconds)
        try:
            checkpoint = executor.execute_chunk(chunk_index, job_id)
        except StageExecutionError as exc:
            control_plane.record_chunk_run(
                conn, chunk_id=chunk_id, status="failed", worker=worker,
                checkpoint={"worker_version": WORKER_VERSION}, error=str(exc),
            )
            control_plane.set_chunk_status(conn, chunk_id=chunk_id, status="failed")
            if on_event is not None:
                on_event("chunk_failed", {"chunk_id": str(chunk_id), "error": str(exc)})
            # Bounded retry: further attempts arrive through the Studio
            # retry operation, which appends a new ChunkRun row.
            max_attempts = _chunk_max_attempts(conn, chunk_id=chunk_id)
            attempt = conn.execute(
                "SELECT attempt FROM chronicle.ingestion_chunks WHERE chunk_id = %s",
                (chunk_id,),
            ).fetchone()[0]
            if int(attempt) >= max_attempts:
                return "needs_review"
            return "failed"
        control_plane.record_chunk_run(
            conn, chunk_id=chunk_id, status="completed", worker=worker,
            checkpoint=checkpoint,
        )
        control_plane.set_chunk_status(conn, chunk_id=chunk_id, status="completed")
        if on_event is not None:
            on_event("chunk_completed", {"chunk_id": str(chunk_id)})
    return "ok"


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
    """Execute one claimed job through the 8-stage pipeline; returns outcome.

    Outcomes: ``"completed"``, ``"failed"`` (stage/chunk fault recorded, job
    parked for bounded Studio retry), ``"needs_review"`` (chunk attempts
    exhausted; a review gate now owns the job), ``"cancelled"`` (halt
    requested via Studio; completed checkpoints preserved), ``"stopped"``
    (graceful shutdown; the ``running`` lease expires for reclaim).
    """
    executor = executor or StageExecutor()
    stop = stop or threading.Event()
    halt = _check_cancelled_or_stop(conn, job_id=job_id, stop=stop)
    if halt is not None:
        return halt
    for stage in control_plane.STAGE_NAMES:
        halt = _check_cancelled_or_stop(conn, job_id=job_id, stop=stop)
        if halt is not None:
            return halt
        stage_status = conn.execute(
            """
            SELECT status FROM chronicle.ingestion_job_stages
            WHERE job_id = %s AND stage = %s
            """,
            (job_id, stage),
        ).fetchone()[0]
        if stage_status in ("completed", "skipped"):
            continue  # checkpoint skip: never re-run succeeded work
        if stage_status in ("pending", "failed", "needs_review"):
            control_plane.advance_stage(
                conn, job_id=job_id, stage=stage, status="running"
            )
        # A `running` stage is worker re-entry after a crash: the
        # checkpointed state is authoritative, so execution resumes in place.
        _heartbeat_best_effort(
            conn, job_id=job_id, worker=worker, lease_seconds=lease_seconds
        )
        if stage == CHUNK_BEARING_STAGE:
            _, chunk_ids = ensure_fake_topology(conn, job_id=job_id, worker=worker)
            outcome = execute_chunks(
                conn, job_id=job_id, chunk_ids=chunk_ids, worker=worker,
                executor=executor, lease_seconds=lease_seconds, stop=stop,
                on_event=on_event,
            )
            if outcome == "ok":
                control_plane.advance_stage(
                    conn, job_id=job_id, stage=stage, status="completed"
                )
                if on_event is not None:
                    on_event("stage_completed", {"stage": stage})
            elif outcome == "failed":
                control_plane.advance_stage(
                    conn, job_id=job_id, stage=stage, status="failed",
                    error="fake chunk fault (bounded retry via Studio)",
                )
                control_plane.set_job_status(
                    conn, job_id=job_id, status="failed",
                    error="fake chunk fault (bounded retry via Studio)",
                )
                return "failed"
            elif outcome == "needs_review":
                control_plane.advance_stage(
                    conn, job_id=job_id, stage=stage, status="needs_review",
                    error="chunk attempts exhausted; awaiting review",
                )
                control_plane.open_review_item(
                    conn, job_id=job_id, kind="chunk_failure",
                    payload={"stage": stage, "worker": worker},
                )
                control_plane.set_job_status(
                    conn, job_id=job_id, status="needs_review",
                    error="chunk attempts exhausted; awaiting review",
                )
                return "needs_review"
            else:  # cancelled / stopped: checkpoints stay as written
                return outcome
        else:
            try:
                checkpoint = executor.execute_stage(stage, job_id)
            except StageExecutionError as exc:
                control_plane.advance_stage(
                    conn, job_id=job_id, stage=stage, status="failed", error=str(exc)
                )
                control_plane.set_job_status(
                    conn, job_id=job_id, status="failed", error=str(exc)
                )
                if on_event is not None:
                    on_event(
                        "stage_failed",
                        {"stage": stage, "error": str(exc)},
                    )
                return "failed"
            conn.execute(
                """
                UPDATE chronicle.ingestion_job_stages
                SET checkpoint = %s WHERE job_id = %s AND stage = %s
                """,
                (Jsonb(checkpoint), job_id, stage),
            )
            control_plane.advance_stage(
                conn, job_id=job_id, stage=stage, status="completed"
            )
            if on_event is not None:
                on_event("stage_completed", {"stage": stage})
    halt = _check_cancelled_or_stop(conn, job_id=job_id, stop=stop)
    if halt is not None:
        return halt
    _heartbeat_best_effort(
        conn, job_id=job_id, worker=worker, lease_seconds=lease_seconds
    )
    status, _, _ = _job_status(conn, job_id=job_id)
    if status == "needs_review":
        return "needs_review"
    _record, revision_id = _job_revision(conn, job_id=job_id)
    control_plane.record_output(
        conn, job_id=job_id, revision_id=revision_id,
        artifact_type=FAKE_OUTPUT_TYPE,
        artifact_sha256=_fake_sha(str(job_id), FAKE_OUTPUT_TYPE),
        payload={"worker_version": WORKER_VERSION, "stages": list(control_plane.STAGE_NAMES)},
    )
    control_plane.set_job_status(conn, job_id=job_id, status="completed")
    if on_event is not None:
        on_event("job_completed", {"job_id": str(job_id)})
    return "completed"


def _job_revision(conn, *, job_id: uuid.UUID) -> tuple[Any, uuid.UUID]:
    row = conn.execute(
        "SELECT job_id, revision_id FROM chronicle.ingestion_jobs WHERE job_id = %s",
        (job_id,),
    ).fetchone()
    if row is None:
        raise PersistenceError(f"unknown job {job_id}")
    return row[0], row[1]


def run_once(
    database_url: str,
    *,
    worker: str,
    executor: StageExecutor | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    stop: threading.Event | None = None,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    job_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, str] | None:
    """Claim one job (queued, or expired-lease running) and execute it.

    Returns ``(job_id, outcome)`` or ``None`` when no job is claimable.
    """
    stop = stop or threading.Event()
    with psycopg.connect(database_url) as conn:
        claimed = control_plane.claim_job(
            conn, worker=worker, lease_seconds=lease_seconds, job_id=job_id
        )
        if claimed is None:
            return None
        try:
            outcome = execute_job(
                conn, job_id=claimed, worker=worker, executor=executor,
                lease_seconds=lease_seconds, stop=stop, on_event=on_event,
            )
        except StopRequested:
            outcome = "stopped"
        return claimed, outcome


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
        if outcome in ("stopped", "cancelled"):
            # A stop/cancel halt concerns this worker's run loop as well as
            # the job: cancelled work must not be immediately re-polled into
            # a tight loop by the same process.
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
    stop = threading.Event()
    install_shutdown_handlers(stop)
    print(
        f"chronicle-worker: {worker} claiming from Chronicle PostgreSQL "
        f"(lease {args.lease_seconds}s)",
        flush=True,
    )
    tally = run_forever(
        database_url, worker=worker,
        executor_factory=lambda: StageExecutor(fail_plan=dict(fail_plan)),
        lease_seconds=args.lease_seconds, poll_interval=args.poll_interval,
        max_jobs=args.max_jobs, stop=stop,
        on_event=lambda event, payload: print(
            f"chronicle-worker: {event} {payload}", flush=True
        ),
    )
    print(f"chronicle-worker: shutdown {tally}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
