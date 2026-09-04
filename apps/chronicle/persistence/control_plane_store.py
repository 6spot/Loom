"""Chronicle C1 ingestion control-plane store (application-owned orchestration).

This module owns the durable lifecycle of C1 document ingestion: documents,
immutable revisions with non-destructive supersession, restart-safe
ingestion jobs with worker leases and checkpoints, pipeline stages, sections,
chunks, append-only chunk runs, review items, and assembled outputs.

Authority boundary (Amendment 0006): this is Chronicle application-owned
product persistence behind CHRONICLE_DATABASE_URL. It is not Loom Runtime
Scheduler/Work authority and never touches Loom engine tables. Assembled
outputs feed the existing C0 staged -> resolution -> canonical path; they do
not replace it.

Status vocabularies are frozen by C1-T1 (GitHub #490) and mirrored by the
standalone Rust domain crate under apps/chronicle/control_plane. Transition
legality is enforced here before any UPDATE reaches PostgreSQL.
"""

from __future__ import annotations

import secrets
import time
import uuid
from typing import Any

from psycopg import errors
from psycopg.types.json import Jsonb

from common import PersistenceConflict, PersistenceError

PIPELINE_ORDER = (
    "prepare",
    "structure",
    "segment",
    "extract",
    "assemble",
    "resolve",
    "publish",
    "present",
)

JOB_STATUSES = frozenset(
    {"queued", "running", "needs_review", "failed", "cancelled", "completed"}
)
STAGE_STATUSES = frozenset(
    {"pending", "running", "needs_review", "failed", "skipped", "completed"}
)
CHUNK_STATUSES = frozenset(
    {"pending", "processing", "needs_review", "failed", "completed"}
)
RUN_STATUSES = frozenset({"started", "succeeded", "failed"})
REVIEW_STATUSES = frozenset({"open", "approved", "rejected", "superseded"})

# Legal transitions, mirrored by the Rust control-plane domain crate.
JOB_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"needs_review", "failed", "cancelled", "completed"}),
    "needs_review": frozenset({"running", "failed", "cancelled", "completed"}),
    "failed": frozenset({"running", "cancelled"}),
    "cancelled": frozenset(),
    "completed": frozenset(),
}

STAGE_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"running", "skipped"}),
    "running": frozenset({"needs_review", "failed", "skipped", "completed"}),
    "needs_review": frozenset({"running", "failed", "skipped", "completed"}),
    "failed": frozenset({"running", "skipped"}),
    "skipped": frozenset({"running"}),
    "completed": frozenset(),
}

CHUNK_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"processing"}),
    "processing": frozenset({"needs_review", "failed", "completed"}),
    "needs_review": frozenset({"processing", "failed", "completed"}),
    "failed": frozenset({"processing"}),
    "completed": frozenset(),
}

RUN_TRANSITIONS: dict[str, frozenset[str]] = {
    "started": frozenset({"succeeded", "failed"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
}

REVIEW_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"approved", "rejected", "superseded"}),
    "approved": frozenset(),
    "rejected": frozenset(),
    "superseded": frozenset(),
}

TERMINAL_JOB_STATUSES = frozenset({"failed", "cancelled", "completed"})


def new_uuid7() -> str:
    """Generate a random UUIDv7 string using only the standard library."""
    unix_ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (
        (unix_ms << 80)
        | (0x7 << 76)
        | (rand_a << 64)
        | (0b10 << 62)
        | rand_b
    )
    return str(uuid.UUID(int=value))


def _coerce_uuid7(value: str | None, description: str) -> str:
    candidate = value or new_uuid7()
    try:
        parsed = uuid.UUID(str(candidate))
    except (ValueError, AttributeError) as exc:
        raise PersistenceError(f"{description} is not a valid UUID: {candidate!r}") from exc
    if parsed.version != 7:
        raise PersistenceError(f"{description} must be UUIDv7: {candidate!r}")
    return str(parsed)


def _check_transition(
    kind: str,
    table: dict[str, frozenset[str]],
    current: str,
    target: str,
) -> None:
    allowed = table.get(current)
    if allowed is None:
        raise PersistenceError(f"unknown {kind} status: {current!r}")
    if target not in table:
        raise PersistenceError(f"unknown {kind} status: {target!r}")
    if target not in allowed:
        raise PersistenceConflict(
            f"illegal {kind} transition: {current!r} -> {target!r}"
        )


def _unique_violation(exc: Exception, description: str) -> PersistenceConflict:
    return PersistenceConflict(f"{description}: {exc}")


# ---------------------------------------------------------------------------
# Documents and revisions
# ---------------------------------------------------------------------------


def create_document(conn, *, title: str, document_id: str | None = None) -> str:
    if not isinstance(title, str) or not 1 <= len(title) <= 500:
        raise PersistenceError("document title must be 1..500 characters")
    resolved = _coerce_uuid7(document_id, "document_id")
    try:
        with conn.transaction():
            conn.execute(
                "INSERT INTO chronicle.documents(document_id, title) VALUES (%s, %s)",
                (resolved, title),
            )
    except errors.UniqueViolation as exc:
        raise _unique_violation(exc, f"document {resolved} already exists") from exc
    return resolved


def create_revision(
    conn,
    *,
    document_id: str,
    source_ref: str,
    source_sha256: str,
    source_length_bytes: int,
    source_media_type: str = "application/octet-stream",
    manifest: dict[str, Any] | None = None,
    supersedes_revision_id: str | None = None,
    revision_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(source_ref, str) or not 1 <= len(source_ref) <= 1000:
        raise PersistenceError("source_ref must be 1..1000 characters")
    if not isinstance(source_sha256, str) or len(source_sha256) != 64:
        raise PersistenceError("source_sha256 must be a 64-char hex digest")
    if not isinstance(source_length_bytes, int) or source_length_bytes < 0:
        raise PersistenceError("source_length_bytes must be a non-negative integer")
    resolved = _coerce_uuid7(revision_id, "revision_id")
    with conn.transaction():
        document = conn.execute(
            "SELECT document_id FROM chronicle.documents WHERE document_id = %s",
            (document_id,),
        ).fetchone()
        if document is None:
            raise PersistenceError(f"document {document_id} does not exist")
        if supersedes_revision_id is None:
            existing = conn.execute(
                "SELECT count(*) FROM chronicle.document_revisions WHERE document_id = %s",
                (document_id,),
            ).fetchone()[0]
            if existing:
                raise PersistenceConflict(
                    "replacing a source requires supersedes_revision_id; "
                    "revisions are never overwritten"
                )
            revision_number = 1
        else:
            row = conn.execute(
                """
                SELECT document_id, revision_number
                FROM chronicle.document_revisions WHERE revision_id = %s
                """,
                (supersedes_revision_id,),
            ).fetchone()
            if row is None:
                raise PersistenceError(
                    f"superseded revision {supersedes_revision_id} does not exist"
                )
            if str(row[0]) != str(document_id):
                raise PersistenceConflict(
                    "revision supersession must stay within one document"
                )
            revision_number = int(row[1]) + 1
        try:
            conn.execute(
                """
                INSERT INTO chronicle.document_revisions(
                    revision_id, document_id, revision_number, source_ref,
                    source_media_type, source_sha256, source_length_bytes,
                    manifest, supersedes_revision_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    resolved,
                    document_id,
                    revision_number,
                    source_ref,
                    source_media_type,
                    source_sha256,
                    source_length_bytes,
                    Jsonb(manifest or {}),
                    supersedes_revision_id,
                ),
            )
        except errors.UniqueViolation as exc:
            raise _unique_violation(
                exc, f"revision for document {document_id} conflicts"
            ) from exc
    return {
        "revision_id": resolved,
        "document_id": document_id,
        "revision_number": revision_number,
        "supersedes_revision_id": supersedes_revision_id,
    }


def get_revision(conn, revision_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT revision_id::text, document_id::text, revision_number, source_ref,
               source_media_type, source_sha256, source_length_bytes,
               manifest, supersedes_revision_id::text, created_at
        FROM chronicle.document_revisions WHERE revision_id = %s
        """,
        (revision_id,),
    ).fetchone()
    if row is None:
        raise PersistenceError(f"revision {revision_id} does not exist")
    keys = (
        "revision_id",
        "document_id",
        "revision_number",
        "source_ref",
        "source_media_type",
        "source_sha256",
        "source_length_bytes",
        "manifest",
        "supersedes_revision_id",
        "created_at",
    )
    return dict(zip(keys, row, strict=True))


# ---------------------------------------------------------------------------
# Jobs, leases, and stages
# ---------------------------------------------------------------------------


def queue_job(
    conn,
    *,
    document_id: str,
    revision_id: str,
    priority: int = 0,
    max_attempts: int = 3,
    job_id: str | None = None,
) -> str:
    resolved = _coerce_uuid7(job_id, "job_id")
    if max_attempts < 1:
        raise PersistenceError("max_attempts must be >= 1")
    with conn.transaction():
        revision = conn.execute(
            "SELECT document_id FROM chronicle.document_revisions WHERE revision_id = %s",
            (revision_id,),
        ).fetchone()
        if revision is None:
            raise PersistenceError(f"revision {revision_id} does not exist")
        if str(revision[0]) != str(document_id):
            raise PersistenceConflict("job revision must belong to the job document")
        try:
            conn.execute(
                """
                INSERT INTO chronicle.ingestion_jobs(
                    job_id, document_id, revision_id, status, priority, max_attempts
                ) VALUES (%s, %s, %s, 'queued', %s, %s)
                """,
                (resolved, document_id, revision_id, priority, max_attempts),
            )
        except errors.UniqueViolation as exc:
            raise _unique_violation(exc, f"job {resolved} already exists") from exc
        for order, stage in enumerate(PIPELINE_ORDER):
            conn.execute(
                """
                INSERT INTO chronicle.ingestion_job_stages(job_id, stage, status, stage_order)
                VALUES (%s, %s, 'pending', %s)
                """,
                (resolved, stage, order),
            )
    return resolved


def get_job(conn, job_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT job_id::text, document_id::text, revision_id::text, status,
               priority, worker_id, lease_expires_at, heartbeat_at,
               attempt_count, max_attempts, checkpoint, error,
               queued_at, started_at, finished_at
        FROM chronicle.ingestion_jobs WHERE job_id = %s
        """,
        (job_id,),
    ).fetchone()
    if row is None:
        raise PersistenceError(f"job {job_id} does not exist")
    keys = (
        "job_id",
        "document_id",
        "revision_id",
        "status",
        "priority",
        "worker_id",
        "lease_expires_at",
        "heartbeat_at",
        "attempt_count",
        "max_attempts",
        "checkpoint",
        "error",
        "queued_at",
        "started_at",
        "finished_at",
    )
    return dict(zip(keys, row, strict=True))


def claim_job(conn, *, worker_id: str, lease_seconds: int = 300) -> dict[str, Any] | None:
    """Claim the next queued (or lease-expired) job for a worker.

    Uses SELECT ... FOR UPDATE SKIP LOCKED so concurrent workers never claim
    the same job. Restart recovery falls out naturally: a job whose worker
    died holds an expired lease and becomes claimable again with its
    checkpoint intact.
    """
    if not worker_id or len(worker_id) > 200:
        raise PersistenceError("worker_id must be 1..200 characters")
    if lease_seconds < 1:
        raise PersistenceError("lease_seconds must be >= 1")
    with conn.transaction():
        row = conn.execute(
            """
            SELECT job_id::text, status
            FROM chronicle.ingestion_jobs
            WHERE status = 'queued'
               OR (status = 'running'
                   AND (lease_expires_at IS NULL OR lease_expires_at < now()))
            ORDER BY CASE WHEN status = 'running' THEN 0 ELSE 1 END,
                     priority DESC, queued_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        ).fetchone()
        if row is None:
            return None
        job_id, status = row
        conn.execute(
            """
            UPDATE chronicle.ingestion_jobs
            SET status = 'running',
                worker_id = %s,
                lease_expires_at = now() + make_interval(secs => %s),
                heartbeat_at = now(),
                attempt_count = attempt_count + 1,
                started_at = COALESCE(started_at, now()),
                updated_at = now()
            WHERE job_id = %s
            """,
            (worker_id, float(lease_seconds), job_id),
        )
    return get_job(conn, job_id)


def heartbeat_job(conn, *, job_id: str, worker_id: str, lease_seconds: int = 300) -> None:
    with conn.transaction():
        row = conn.execute(
            "SELECT worker_id, status FROM chronicle.ingestion_jobs WHERE job_id = %s FOR UPDATE",
            (job_id,),
        ).fetchone()
        if row is None:
            raise PersistenceError(f"job {job_id} does not exist")
        if row[0] != worker_id:
            raise PersistenceConflict(
                f"job {job_id} is leased to a different worker"
            )
        if row[1] != "running":
            raise PersistenceConflict(
                f"heartbeat requires a running job (got {row[1]!r})"
            )
        conn.execute(
            """
            UPDATE chronicle.ingestion_jobs
            SET lease_expires_at = now() + make_interval(secs => %s),
                heartbeat_at = now(),
                updated_at = now()
            WHERE job_id = %s
            """,
            (float(lease_seconds), job_id),
        )


def save_job_checkpoint(
    conn,
    job_id: str,
    checkpoint: dict[str, Any],
    *,
    worker_id: str | None = None,
) -> dict[str, Any]:
    """Persist orchestration progress without changing job status.

    Heartbeats prove liveness; checkpoints prove progress. A crashed worker
    restarts from the last checkpoint instead of from scratch.
    """
    with conn.transaction():
        row = conn.execute(
            "SELECT status, worker_id FROM chronicle.ingestion_jobs WHERE job_id = %s FOR UPDATE",
            (job_id,),
        ).fetchone()
        if row is None:
            raise PersistenceError(f"job {job_id} does not exist")
        if row[0] in ("cancelled", "completed"):
            raise PersistenceConflict(
                f"cannot checkpoint a {row[0]} job"
            )
        if worker_id is not None and row[1] != worker_id:
            raise PersistenceConflict(f"job {job_id} is leased to a different worker")
        conn.execute(
            """
            UPDATE chronicle.ingestion_jobs
            SET checkpoint = %s, updated_at = now()
            WHERE job_id = %s
            """,
            (Jsonb(checkpoint), job_id),
        )
    return get_job(conn, job_id)


def transition_job(
    conn,
    job_id: str,
    to_status: str,
    *,
    error: dict[str, Any] | None = None,
    checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if to_status not in JOB_STATUSES:
        raise PersistenceError(f"unknown job status: {to_status!r}")
    with conn.transaction():
        row = conn.execute(
            "SELECT status FROM chronicle.ingestion_jobs WHERE job_id = %s FOR UPDATE",
            (job_id,),
        ).fetchone()
        if row is None:
            raise PersistenceError(f"job {job_id} does not exist")
        _check_transition("job", JOB_TRANSITIONS, row[0], to_status)
        finished = "finished_at = now()," if to_status in TERMINAL_JOB_STATUSES else ""
        conn.execute(
            f"""
            UPDATE chronicle.ingestion_jobs
            SET status = %s, {finished} updated_at = now(),
                error = COALESCE(%s, error),
                checkpoint = COALESCE(%s, checkpoint)
            WHERE job_id = %s
            """,
            (to_status, Jsonb(error) if error is not None else None,
             Jsonb(checkpoint) if checkpoint is not None else None, job_id),
        )
    return get_job(conn, job_id)


def get_stages(conn, job_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT stage, status, stage_order, attempt_count, checkpoint, error,
               started_at, finished_at
        FROM chronicle.ingestion_job_stages
        WHERE job_id = %s ORDER BY stage_order
        """,
        (job_id,),
    ).fetchall()
    keys = (
        "stage",
        "status",
        "stage_order",
        "attempt_count",
        "checkpoint",
        "error",
        "started_at",
        "finished_at",
    )
    return [dict(zip(keys, row, strict=True)) for row in rows]


def transition_stage(
    conn,
    job_id: str,
    stage: str,
    to_status: str,
    *,
    error: dict[str, Any] | None = None,
    checkpoint: dict[str, Any] | None = None,
) -> None:
    if stage not in PIPELINE_ORDER:
        raise PersistenceError(f"unknown pipeline stage: {stage!r}")
    if to_status not in STAGE_STATUSES:
        raise PersistenceError(f"unknown stage status: {to_status!r}")
    with conn.transaction():
        row = conn.execute(
            """
            SELECT status FROM chronicle.ingestion_job_stages
            WHERE job_id = %s AND stage = %s FOR UPDATE
            """,
            (job_id, stage),
        ).fetchone()
        if row is None:
            raise PersistenceError(f"stage {stage!r} of job {job_id} does not exist")
        _check_transition("stage", STAGE_TRANSITIONS, row[0], to_status)
        started = "started_at = COALESCE(started_at, now())," if to_status == "running" else ""
        finished = (
            "finished_at = now(),"
            if to_status in ("failed", "skipped", "completed")
            else "finished_at = NULL,"
        )
        conn.execute(
            f"""
            UPDATE chronicle.ingestion_job_stages
            SET status = %s, {started} {finished}
                attempt_count = attempt_count + %s,
                updated_at = now(),
                error = COALESCE(%s, error),
                checkpoint = COALESCE(%s, checkpoint)
            WHERE job_id = %s AND stage = %s
            """,
            (
                to_status,
                1 if to_status == "running" else 0,
                Jsonb(error) if error is not None else None,
                Jsonb(checkpoint) if checkpoint is not None else None,
                job_id,
                stage,
            ),
        )


# ---------------------------------------------------------------------------
# Sections, chunks, and runs
# ---------------------------------------------------------------------------


def create_section(
    conn,
    *,
    job_id: str,
    revision_id: str,
    section_index: int,
    section_kind: str = "body",
    title: str = "",
    source_start_offset: int = 0,
    source_end_offset: int = 0,
    section_id: str | None = None,
) -> str:
    resolved = _coerce_uuid7(section_id, "section_id")
    if section_index < 0 or source_start_offset < 0 or source_end_offset < 0:
        raise PersistenceError("section offsets/index must be non-negative")
    if source_start_offset > source_end_offset:
        raise PersistenceError("section start must not exceed section end")
    with conn.transaction():
        try:
            conn.execute(
                """
                INSERT INTO chronicle.ingestion_sections(
                    section_id, job_id, revision_id, section_index,
                    section_kind, title, source_start_offset, source_end_offset
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    resolved,
                    job_id,
                    revision_id,
                    section_index,
                    section_kind,
                    title,
                    source_start_offset,
                    source_end_offset,
                ),
            )
        except errors.UniqueViolation as exc:
            raise _unique_violation(exc, "section coordinate already exists") from exc
    return resolved


def create_chunk(
    conn,
    *,
    job_id: str,
    section_id: str,
    revision_id: str,
    chunk_index: int,
    source_start_offset: int,
    source_end_offset: int,
    source_sha256: str,
    coordinates: dict[str, Any] | None = None,
    max_retries: int = 3,
    chunk_id: str | None = None,
) -> str:
    resolved = _coerce_uuid7(chunk_id, "chunk_id")
    if chunk_index < 0 or source_start_offset < 0 or source_end_offset < 0:
        raise PersistenceError("chunk offsets/index must be non-negative")
    if source_start_offset > source_end_offset:
        raise PersistenceError("chunk start must not exceed chunk end")
    with conn.transaction():
        try:
            conn.execute(
                """
                INSERT INTO chronicle.ingestion_chunks(
                    chunk_id, job_id, section_id, revision_id, chunk_index,
                    status, source_start_offset, source_end_offset,
                    source_sha256, coordinates, max_retries
                ) VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s)
                """,
                (
                    resolved,
                    job_id,
                    section_id,
                    revision_id,
                    chunk_index,
                    source_start_offset,
                    source_end_offset,
                    source_sha256,
                    Jsonb(coordinates or {}),
                    max_retries,
                ),
            )
        except errors.UniqueViolation as exc:
            raise _unique_violation(exc, "chunk coordinate already exists") from exc
    return resolved


def get_chunk(conn, chunk_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT chunk_id::text, job_id::text, section_id::text, revision_id::text,
               chunk_index, status, source_start_offset, source_end_offset,
               source_sha256, coordinates, retry_count, max_retries, next_retry_at
        FROM chronicle.ingestion_chunks WHERE chunk_id = %s
        """,
        (chunk_id,),
    ).fetchone()
    if row is None:
        raise PersistenceError(f"chunk {chunk_id} does not exist")
    keys = (
        "chunk_id",
        "job_id",
        "section_id",
        "revision_id",
        "chunk_index",
        "status",
        "source_start_offset",
        "source_end_offset",
        "source_sha256",
        "coordinates",
        "retry_count",
        "max_retries",
        "next_retry_at",
    )
    return dict(zip(keys, row, strict=True))


def transition_chunk(conn, chunk_id: str, to_status: str) -> dict[str, Any]:
    if to_status not in CHUNK_STATUSES:
        raise PersistenceError(f"unknown chunk status: {to_status!r}")
    with conn.transaction():
        row = conn.execute(
            """
            SELECT status, retry_count FROM chronicle.ingestion_chunks
            WHERE chunk_id = %s FOR UPDATE
            """,
            (chunk_id,),
        ).fetchone()
        if row is None:
            raise PersistenceError(f"chunk {chunk_id} does not exist")
        _check_transition("chunk", CHUNK_TRANSITIONS, row[0], to_status)
        extra = ""
        if to_status == "processing" and row[0] == "failed":
            extra = "retry_count = retry_count + 1,"
        conn.execute(
            f"""
            UPDATE chronicle.ingestion_chunks
            SET status = %s, {extra} updated_at = now()
            WHERE chunk_id = %s
            """,
            (to_status, chunk_id),
        )
    return get_chunk(conn, chunk_id)


def start_chunk_run(
    conn,
    *,
    chunk_id: str,
    job_id: str,
    attempt_number: int,
    worker_id: str | None = None,
    checkpoint: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> str:
    resolved = _coerce_uuid7(run_id, "run_id")
    if attempt_number < 1:
        raise PersistenceError("attempt_number must be >= 1")
    with conn.transaction():
        try:
            conn.execute(
                """
                INSERT INTO chronicle.ingestion_chunk_runs(
                    run_id, chunk_id, job_id, attempt_number, status,
                    worker_id, checkpoint
                ) VALUES (%s, %s, %s, %s, 'started', %s, %s)
                """,
                (
                    resolved,
                    chunk_id,
                    job_id,
                    attempt_number,
                    worker_id,
                    Jsonb(checkpoint or {}),
                ),
            )
        except errors.UniqueViolation as exc:
            raise _unique_violation(exc, "chunk run already recorded") from exc
    return resolved


def finish_chunk_run(
    conn,
    run_id: str,
    to_status: str,
    *,
    error: dict[str, Any] | None = None,
    checkpoint: dict[str, Any] | None = None,
) -> None:
    if to_status not in ("succeeded", "failed"):
        raise PersistenceError(f"run completion must be succeeded/failed (got {to_status!r})")
    with conn.transaction():
        row = conn.execute(
            "SELECT status FROM chronicle.ingestion_chunk_runs WHERE run_id = %s FOR UPDATE",
            (run_id,),
        ).fetchone()
        if row is None:
            raise PersistenceError(f"chunk run {run_id} does not exist")
        _check_transition("chunk run", RUN_TRANSITIONS, row[0], to_status)
        conn.execute(
            """
            UPDATE chronicle.ingestion_chunk_runs
            SET status = %s, finished_at = now(),
                error = COALESCE(%s, error),
                checkpoint = COALESCE(%s, checkpoint)
            WHERE run_id = %s
            """,
            (
                to_status,
                Jsonb(error) if error is not None else None,
                Jsonb(checkpoint) if checkpoint is not None else None,
                run_id,
            ),
        )


# ---------------------------------------------------------------------------
# Reviews and outputs
# ---------------------------------------------------------------------------


def open_review(
    conn,
    *,
    job_id: str,
    revision_id: str,
    kind: str,
    chunk_id: str | None = None,
    stage: str | None = None,
    payload: dict[str, Any] | None = None,
    review_id: str | None = None,
) -> str:
    resolved = _coerce_uuid7(review_id, "review_id")
    if kind not in ("segmentation", "extraction", "resolution_decision",
                    "assembly", "publication", "other"):
        raise PersistenceError(f"unknown review kind: {kind!r}")
    if stage is not None and stage not in PIPELINE_ORDER:
        raise PersistenceError(f"unknown pipeline stage: {stage!r}")
    with conn.transaction():
        try:
            conn.execute(
                """
                INSERT INTO chronicle.review_items(
                    review_id, job_id, revision_id, chunk_id, stage, kind,
                    status, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, 'open', %s)
                """,
                (
                    resolved,
                    job_id,
                    revision_id,
                    chunk_id,
                    stage,
                    kind,
                    Jsonb(payload or {}),
                ),
            )
        except errors.UniqueViolation as exc:
            raise _unique_violation(exc, "review item already exists") from exc
    return resolved


def resolve_review(
    conn,
    review_id: str,
    to_status: str,
    *,
    resolution: dict[str, Any] | None = None,
) -> None:
    if to_status not in ("approved", "rejected", "superseded"):
        raise PersistenceError(
            f"review resolution must be approved/rejected/superseded (got {to_status!r})"
        )
    with conn.transaction():
        row = conn.execute(
            "SELECT status FROM chronicle.review_items WHERE review_id = %s FOR UPDATE",
            (review_id,),
        ).fetchone()
        if row is None:
            raise PersistenceError(f"review {review_id} does not exist")
        _check_transition("review", REVIEW_TRANSITIONS, row[0], to_status)
        conn.execute(
            """
            UPDATE chronicle.review_items
            SET status = %s, resolved_at = now(),
                resolution = COALESCE(%s, resolution)
            WHERE review_id = %s
            """,
            (
                to_status,
                Jsonb(resolution) if resolution is not None else None,
                review_id,
            ),
        )


def open_reviews(conn, job_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT review_id::text, chunk_id::text, stage, kind, status, payload
        FROM chronicle.review_items
        WHERE job_id = %s AND status = 'open' ORDER BY created_at
        """,
        (job_id,),
    ).fetchall()
    keys = ("review_id", "chunk_id", "stage", "kind", "status", "payload")
    return [dict(zip(keys, row, strict=True)) for row in rows]


def publish_output(
    conn,
    *,
    job_id: str,
    revision_id: str,
    output_kind: str,
    artifact_sha256: str,
    payload: dict[str, Any],
    output_id: str | None = None,
) -> str:
    resolved = _coerce_uuid7(output_id, "output_id")
    if output_kind not in (
        "staged_bundle",
        "resolution_links",
        "canonical_catalog",
        "report",
        "other",
    ):
        raise PersistenceError(f"unknown output kind: {output_kind!r}")
    with conn.transaction():
        try:
            conn.execute(
                """
                INSERT INTO chronicle.ingestion_outputs(
                    output_id, job_id, revision_id, output_kind,
                    artifact_sha256, payload
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    resolved,
                    job_id,
                    revision_id,
                    output_kind,
                    artifact_sha256,
                    Jsonb(payload),
                ),
            )
        except errors.UniqueViolation as exc:
            raise _unique_violation(exc, "ingestion output already published") from exc
    return resolved


def job_provenance(conn, job_id: str) -> dict[str, Any]:
    """Trace everything a job produced back to its immutable revision."""
    job = get_job(conn, job_id)
    revision = get_revision(conn, job["revision_id"])
    stages = get_stages(conn, job_id)
    chunks = conn.execute(
        """
        SELECT chunk_id::text, section_id::text, chunk_index, status,
               source_start_offset, source_end_offset, source_sha256, retry_count
        FROM chronicle.ingestion_chunks
        WHERE job_id = %s ORDER BY chunk_index
        """,
        (job_id,),
    ).fetchall()
    runs = conn.execute(
        """
        SELECT run_id::text, chunk_id::text, attempt_number, status, worker_id
        FROM chronicle.ingestion_chunk_runs
        WHERE job_id = %s ORDER BY attempt_number
        """,
        (job_id,),
    ).fetchall()
    reviews = conn.execute(
        "SELECT review_id::text, status FROM chronicle.review_items WHERE job_id = %s",
        (job_id,),
    ).fetchall()
    outputs = conn.execute(
        """
        SELECT output_id::text, output_kind, artifact_sha256
        FROM chronicle.ingestion_outputs WHERE job_id = %s
        """,
        (job_id,),
    ).fetchall()
    return {
        "job": job,
        "revision": revision,
        "stages": stages,
        "chunks": chunks,
        "runs": runs,
        "reviews": reviews,
        "outputs": outputs,
    }
