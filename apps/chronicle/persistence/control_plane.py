"""Chronicle C1-T1 ingestion control-plane store (application-owned persistence).

This module owns the durable lifecycle of complete historical documents as
restart-safe ingestion workflows: Document -> immutable DocumentRevision ->
IngestionJob (+ stages, sections, chunks, chunk runs, review items, outputs).

Transition tables here mirror `apps/chronicle/control_plane/src/lib.rs`
(the Rust control-plane contract). The Rust crate is normative for the state
machine; this module enforces the same transitions at the Python persistence
boundary because C1 workers are Python. If the two disagree, the Rust contract
wins and this module must be updated to match.

Boundary notes (Architecture Amendment 0006):
- This store uses only CHRONICLE_DATABASE_URL and only `chronicle.*`
  control-plane tables plus the untouched C0 tables. It never reads or writes
  Loom Runtime/World/Timeline/Work/Binding state and never imports
  `loom-storage` or `PgStorage`, and never consumes the Loom engine database
  connection contract.
- Chunks are processing units addressed by stable revision/job/section
  coordinates plus source offsets/hashes. They never become historical
  identity/truth boundaries; canonical identity remains owned by the C0
  staged/resolution/canonical path.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import psycopg
import psycopg.errors
from psycopg.types.json import Jsonb

from common import PersistenceConflict, PersistenceError

JOB_STATUSES = ("queued", "running", "needs_review", "failed", "cancelled", "completed")

STAGE_NAMES = (
    "prepare",
    "structure",
    "segment",
    "extract",
    "assemble",
    "resolve",
    "publish",
    "present",
)

STAGE_STATUSES = ("pending", "running", "needs_review", "failed", "skipped", "completed")

CHUNK_STATUSES = ("pending", "running", "needs_review", "failed", "completed")

RUN_STATUSES = ("running", "failed", "completed")

REVIEW_KINDS = ("chunk_failure", "stage_gate", "quality_flag")

REVIEW_STATUSES = ("open", "resolved", "dismissed")

# Legal job transitions. Mirrors Rust `JobStatus::can_transition_to`.
# Terminal states (failed, cancelled, completed) have no outgoing edges.
JOB_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"needs_review", "failed", "cancelled", "completed"}),
    "needs_review": frozenset({"running", "failed", "cancelled"}),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "completed": frozenset(),
}

# Legal stage transitions. Mirrors Rust `StageStatus::can_transition_to`.
STAGE_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"running", "skipped"}),
    "running": frozenset({"needs_review", "failed", "completed", "skipped"}),
    "needs_review": frozenset({"running", "failed", "skipped"}),
    "failed": frozenset({"running"}),
    "skipped": frozenset(),
    "completed": frozenset(),
}

# Legal chunk transitions. Mirrors Rust `ChunkStatus::can_transition_to`.
CHUNK_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"running"}),
    "running": frozenset({"needs_review", "failed", "completed"}),
    "needs_review": frozenset({"running", "failed"}),
    "failed": frozenset({"running"}),
    "completed": frozenset(),
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> uuid.UUID:
    return uuid.uuid4()


def _require_sha256(value: Any, description: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.match(value):
        raise PersistenceError(f"{description} must be a lowercase hex SHA-256 string")
    return value


def _require_status(value: Any, allowed: Iterable[str], description: str) -> str:
    if value not in allowed:
        raise PersistenceError(f"{description} must be one of {sorted(allowed)}, got {value!r}")
    return value


def _check_transition(current: str, nxt: str, transitions: dict[str, frozenset[str]], kind: str) -> None:
    if nxt == current:
        return
    if nxt not in transitions.get(current, frozenset()):
        raise PersistenceConflict(f"illegal {kind} transition: {current!r} -> {nxt!r}")


@dataclass(frozen=True)
class ControlPlaneIds:
    document_id: uuid.UUID
    revision_id: uuid.UUID
    job_id: uuid.UUID


def create_document(conn, *, title: str) -> uuid.UUID:
    """Create a document container. Revisions carry the immutable source."""
    if not isinstance(title, str) or not title:
        raise PersistenceError("document title must be a non-empty string")
    document_id = _new_id()
    with conn.transaction():
        conn.execute(
            "INSERT INTO chronicle.documents(document_id, title) VALUES (%s, %s)",
            (document_id, title),
        )
    return document_id


def create_revision(
    conn,
    *,
    document_id: uuid.UUID,
    source_sha256: str,
    source_bytes: int,
    source_media_type: str,
) -> tuple[uuid.UUID, int]:
    """Append an immutable revision. Never mutates earlier revisions.

    Returns (revision_id, revision_no). The new revision supersedes the
    previous tip when one exists; replacement is non-destructive by
    construction because old rows are append-only (DB trigger enforced).
    """
    _require_sha256(source_sha256, "source_sha256")
    if not isinstance(source_bytes, int) or source_bytes < 0:
        raise PersistenceError("source_bytes must be a non-negative integer")
    if not isinstance(source_media_type, str) or not source_media_type:
        raise PersistenceError("source_media_type must be a non-empty string")
    revision_id = _new_id()
    with conn.transaction():
        tip = conn.execute(
            """
            SELECT revision_id, revision_no
            FROM chronicle.document_revisions
            WHERE document_id = %s
            ORDER BY revision_no DESC
            LIMIT 1
            """,
            (document_id,),
        ).fetchone()
        if tip is None:
            # Fail fast on unknown documents instead of hitting the FK later.
            exists = conn.execute(
                "SELECT 1 FROM chronicle.documents WHERE document_id = %s",
                (document_id,),
            ).fetchone()
            if exists is None:
                raise PersistenceError(f"unknown document {document_id}")
            revision_no, supersedes = 1, None
        else:
            revision_no, supersedes = int(tip[1]) + 1, tip[0]
        conn.execute(
            """
            INSERT INTO chronicle.document_revisions(
                revision_id, document_id, revision_no,
                source_sha256, source_bytes, source_media_type,
                supersedes_revision_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                revision_id,
                document_id,
                revision_no,
                source_sha256,
                source_bytes,
                source_media_type,
                supersedes,
            ),
        )
    return revision_id, revision_no


def queue_job(conn, *, revision_id: uuid.UUID, max_attempts: int = 3) -> uuid.UUID:
    """Queue one ingestion job for a revision and seed the 8-stage pipeline."""
    if not isinstance(max_attempts, int) or max_attempts < 1:
        raise PersistenceError("max_attempts must be a positive integer")
    job_id = _new_id()
    with conn.transaction():
        exists = conn.execute(
            "SELECT 1 FROM chronicle.document_revisions WHERE revision_id = %s",
            (revision_id,),
        ).fetchone()
        if exists is None:
            raise PersistenceError(f"unknown revision {revision_id}")
        conn.execute(
            """
            INSERT INTO chronicle.ingestion_jobs(job_id, revision_id, status, max_attempts)
            VALUES (%s, %s, 'queued', %s)
            """,
            (job_id, revision_id, max_attempts),
        )
        for stage in STAGE_NAMES:
            conn.execute(
                """
                INSERT INTO chronicle.ingestion_job_stages(job_id, stage, status)
                VALUES (%s, %s, 'pending')
                """,
                (job_id, stage),
            )
    return job_id


def claim_job(
    conn,
    *,
    worker: str,
    lease_seconds: int = 300,
    job_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Claim a queued job (or one specific job) under a worker lease.

    Returns the claimed job_id, or None when no queued job is claimable.
    Restart-safe: an expired lease may be re-claimed by another worker.
    """
    if not isinstance(worker, str) or not worker:
        raise PersistenceError("worker must be a non-empty string")
    if not isinstance(lease_seconds, int) or lease_seconds < 1:
        raise PersistenceError("lease_seconds must be a positive integer")
    now = _utcnow()
    expires = now + timedelta(seconds=lease_seconds)
    with conn.transaction():
        if job_id is None:
            row = conn.execute(
                """
                SELECT job_id FROM chronicle.ingestion_jobs
                WHERE status = 'queued'
                   OR (status = 'running' AND lease_expires_at IS NOT NULL
                       AND lease_expires_at <= %s)
                ORDER BY created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                (now,),
            ).fetchone()
            if row is None:
                return None
            job_id = row[0]
        current = conn.execute(
            "SELECT status, lease_expires_at FROM chronicle.ingestion_jobs WHERE job_id = %s FOR UPDATE",
            (job_id,),
        ).fetchone()
        if current is None:
            raise PersistenceError(f"unknown job {job_id}")
        status, lease_expires_at = current[0], current[1]
        if status == "queued":
            nxt = "running"
        elif status == "running" and lease_expires_at is not None and lease_expires_at <= now:
            nxt = "running"  # lease takeover after worker loss; stays running
        else:
            raise PersistenceConflict(f"job {job_id} is not claimable from status {status!r}")
        _check_transition(status, nxt, JOB_TRANSITIONS, "job")
        conn.execute(
            """
            UPDATE chronicle.ingestion_jobs
            SET status = %s,
                attempt = attempt + 1,
                lease_owner = %s,
                lease_expires_at = %s,
                updated_at = %s
            WHERE job_id = %s
            """,
            (nxt, worker, expires, now, job_id),
        )
    return job_id


def heartbeat_job(conn, *, job_id: uuid.UUID, worker: str, lease_seconds: int = 300) -> None:
    """Renew a worker lease. Only the lease owner may renew."""
    if not isinstance(worker, str) or not worker:
        raise PersistenceError("worker must be a non-empty string")
    now = _utcnow()
    with conn.transaction():
        row = conn.execute(
            "SELECT lease_owner FROM chronicle.ingestion_jobs WHERE job_id = %s FOR UPDATE",
            (job_id,),
        ).fetchone()
        if row is None:
            raise PersistenceError(f"unknown job {job_id}")
        if row[0] != worker:
            raise PersistenceConflict(f"worker {worker!r} does not own the lease for job {job_id}")
        conn.execute(
            """
            UPDATE chronicle.ingestion_jobs
            SET lease_expires_at = %s, updated_at = %s
            WHERE job_id = %s
            """,
            (now + timedelta(seconds=lease_seconds), now, job_id),
        )


def set_job_status(
    conn, *, job_id: uuid.UUID, status: str, error: str | None = None
) -> None:
    """Move a job to a new status after validating the legal transition."""
    _require_status(status, JOB_STATUSES, "job status")
    with conn.transaction():
        row = conn.execute(
            "SELECT status FROM chronicle.ingestion_jobs WHERE job_id = %s FOR UPDATE",
            (job_id,),
        ).fetchone()
        if row is None:
            raise PersistenceError(f"unknown job {job_id}")
        _check_transition(row[0], status, JOB_TRANSITIONS, "job")
        conn.execute(
            """
            UPDATE chronicle.ingestion_jobs
            SET status = %s, error = %s, updated_at = %s,
                lease_owner = CASE WHEN %s IN ('failed', 'cancelled', 'completed') THEN NULL ELSE lease_owner END,
                lease_expires_at = CASE WHEN %s IN ('failed', 'cancelled', 'completed') THEN NULL ELSE lease_expires_at END
            WHERE job_id = %s
            """,
            (status, error, _utcnow(), status, status, job_id),
        )


def advance_stage(
    conn, *, job_id: uuid.UUID, stage: str, status: str, error: str | None = None
) -> None:
    """Move one pipeline stage to a new status after validating the transition."""
    _require_status(stage, STAGE_NAMES, "stage")
    _require_status(status, STAGE_STATUSES, "stage status")
    with conn.transaction():
        row = conn.execute(
            """
            SELECT status FROM chronicle.ingestion_job_stages
            WHERE job_id = %s AND stage = %s FOR UPDATE
            """,
            (job_id, stage),
        ).fetchone()
        if row is None:
            raise PersistenceError(f"unknown stage {stage!r} for job {job_id}")
        _check_transition(row[0], status, STAGE_TRANSITIONS, "stage")
        conn.execute(
            """
            UPDATE chronicle.ingestion_job_stages
            SET status = %s,
                error = %s,
                attempt = attempt + CASE WHEN %s = 'running' AND status <> 'running' THEN 1 ELSE 0 END,
                started_at = CASE WHEN started_at IS NULL AND %s = 'running' THEN %s ELSE started_at END,
                finished_at = CASE WHEN %s IN ('failed', 'skipped', 'completed') THEN %s ELSE NULL END,
                updated_at = %s
            WHERE job_id = %s AND stage = %s
            """,
            (status, error, status, status, _utcnow(), status, _utcnow(), _utcnow(), job_id, stage),
        )


def create_section(
    conn,
    *,
    job_id: uuid.UUID,
    section_index: int,
    label: str,
    source_start: int,
    source_end: int,
) -> uuid.UUID:
    """Record one ordered processing section scope for a job."""
    if not isinstance(section_index, int) or section_index < 0:
        raise PersistenceError("section_index must be a non-negative integer")
    if not isinstance(label, str) or not label:
        raise PersistenceError("section label must be a non-empty string")
    if not isinstance(source_start, int) or source_start < 0:
        raise PersistenceError("source_start must be a non-negative integer")
    if not isinstance(source_end, int) or source_end < source_start:
        raise PersistenceError("source_end must be >= source_start")
    section_id = _new_id()
    with conn.transaction():
        try:
            conn.execute(
                """
                INSERT INTO chronicle.ingestion_sections(
                    section_id, job_id, section_index, label, source_start, source_end
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (section_id, job_id, section_index, label, source_start, source_end),
            )
        except psycopg.errors.UniqueViolation as exc:
            raise PersistenceConflict(
                f"section ({job_id}, {section_index}) already exists"
            ) from exc
        except psycopg.errors.ForeignKeyViolation as exc:
            raise PersistenceError(f"unknown job {job_id}") from exc
    return section_id


def record_chunk(
    conn,
    *,
    job_id: uuid.UUID,
    section_id: uuid.UUID | None,
    chunk_index: int,
    source_start: int,
    source_end: int,
    source_sha256: str,
    content_sha256: str,
    max_attempts: int = 3,
) -> uuid.UUID:
    """Record one processing chunk with stable job/section coordinates."""
    if not isinstance(chunk_index, int) or chunk_index < 0:
        raise PersistenceError("chunk_index must be a non-negative integer")
    if not isinstance(source_start, int) or source_start < 0:
        raise PersistenceError("source_start must be a non-negative integer")
    if not isinstance(source_end, int) or source_end < source_start:
        raise PersistenceError("source_end must be >= source_start")
    _require_sha256(source_sha256, "source_sha256")
    _require_sha256(content_sha256, "content_sha256")
    chunk_id = _new_id()
    with conn.transaction():
        try:
            conn.execute(
                """
                INSERT INTO chronicle.ingestion_chunks(
                    chunk_id, job_id, section_id, chunk_index,
                    source_start, source_end, source_sha256, content_sha256,
                    max_attempts
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    chunk_id,
                    job_id,
                    section_id,
                    chunk_index,
                    source_start,
                    source_end,
                    source_sha256,
                    content_sha256,
                    max_attempts,
                ),
            )
        except psycopg.errors.UniqueViolation as exc:
            raise PersistenceConflict(
                f"chunk ({job_id}, {chunk_index}) already exists"
            ) from exc
        except psycopg.errors.ForeignKeyViolation as exc:
            raise PersistenceError(f"unknown job or section for chunk ({job_id})") from exc
    return chunk_id


def set_chunk_status(conn, *, chunk_id: uuid.UUID, status: str) -> None:
    """Move a chunk to a new status after validating the legal transition."""
    _require_status(status, CHUNK_STATUSES, "chunk status")
    with conn.transaction():
        row = conn.execute(
            "SELECT status FROM chronicle.ingestion_chunks WHERE chunk_id = %s FOR UPDATE",
            (chunk_id,),
        ).fetchone()
        if row is None:
            raise PersistenceError(f"unknown chunk {chunk_id}")
        _check_transition(row[0], status, CHUNK_TRANSITIONS, "chunk")
        conn.execute(
            """
            UPDATE chronicle.ingestion_chunks
            SET status = %s, updated_at = %s
            WHERE chunk_id = %s
            """,
            (status, _utcnow(), chunk_id),
        )


def record_chunk_run(
    conn,
    *,
    chunk_id: uuid.UUID,
    status: str,
    worker: str,
    checkpoint: dict[str, Any] | None = None,
    error: str | None = None,
) -> tuple[uuid.UUID, int]:
    """Append one attempt run for a chunk. Retries always append a new run row.

    Returns (run_id, attempt). Run rows are append-only history and are never
    mutated afterwards.
    """
    _require_status(status, RUN_STATUSES, "chunk run status")
    if not isinstance(worker, str) or not worker:
        raise PersistenceError("worker must be a non-empty string")
    run_id = _new_id()
    with conn.transaction():
        row = conn.execute(
            "SELECT attempt FROM chronicle.ingestion_chunks WHERE chunk_id = %s FOR UPDATE",
            (chunk_id,),
        ).fetchone()
        if row is None:
            raise PersistenceError(f"unknown chunk {chunk_id}")
        attempt = int(row[0]) + 1
        conn.execute(
            """
            INSERT INTO chronicle.ingestion_chunk_runs(
                run_id, chunk_id, attempt, status, worker, checkpoint, error,
                finished_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                chunk_id,
                attempt,
                status,
                worker,
                Jsonb(checkpoint or {}),
                error,
                _utcnow() if status in ("failed", "completed") else None,
            ),
        )
        conn.execute(
            """
            UPDATE chronicle.ingestion_chunks
            SET attempt = %s, updated_at = %s
            WHERE chunk_id = %s
            """,
            (attempt, _utcnow(), chunk_id),
        )
    return run_id, attempt


def open_review_item(
    conn,
    *,
    job_id: uuid.UUID,
    kind: str,
    chunk_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> uuid.UUID:
    """Open a human review gate for a job (optionally scoped to a chunk)."""
    _require_status(kind, REVIEW_KINDS, "review kind")
    review_id = _new_id()
    with conn.transaction():
        try:
            conn.execute(
                """
                INSERT INTO chronicle.review_items(review_id, job_id, chunk_id, kind, payload)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (review_id, job_id, chunk_id, kind, Jsonb(payload or {})),
            )
        except psycopg.errors.ForeignKeyViolation as exc:
            raise PersistenceError(f"unknown job or chunk for review ({job_id})") from exc
    return review_id


def resolve_review_item(conn, *, review_id: uuid.UUID, status: str = "resolved") -> None:
    """Resolve or dismiss an open review item. Resolved items stay auditable."""
    _require_status(status, ("resolved", "dismissed"), "review resolution")
    with conn.transaction():
        row = conn.execute(
            "SELECT status FROM chronicle.review_items WHERE review_id = %s FOR UPDATE",
            (review_id,),
        ).fetchone()
        if row is None:
            raise PersistenceError(f"unknown review item {review_id}")
        if row[0] != "open":
            raise PersistenceConflict(f"review item {review_id} is already {row[0]!r}")
        conn.execute(
            """
            UPDATE chronicle.review_items
            SET status = %s, resolved_at = %s
            WHERE review_id = %s
            """,
            (status, _utcnow(), review_id),
        )


def open_review_count(conn, *, job_id: uuid.UUID) -> int:
    row = conn.execute(
        "SELECT count(*) FROM chronicle.review_items WHERE job_id = %s AND status = 'open'",
        (job_id,),
    ).fetchone()
    return int(row[0])


def record_output(
    conn,
    *,
    job_id: uuid.UUID,
    revision_id: uuid.UUID,
    artifact_type: str,
    artifact_sha256: str,
    payload: dict[str, Any],
) -> uuid.UUID:
    """Record one assembled ingestion output for an exact (job, revision)."""
    if not isinstance(artifact_type, str) or not artifact_type:
        raise PersistenceError("artifact_type must be a non-empty string")
    _require_sha256(artifact_sha256, "artifact_sha256")
    if not isinstance(payload, dict):
        raise PersistenceError("output payload must be a JSON object")
    output_id = _new_id()
    with conn.transaction():
        try:
            conn.execute(
                """
                INSERT INTO chronicle.ingestion_outputs(
                    output_id, job_id, revision_id, artifact_type, artifact_sha256, payload
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (job_id, artifact_type, artifact_sha256) DO NOTHING
                """,
                (output_id, job_id, revision_id, artifact_type, artifact_sha256, Jsonb(payload)),
            )
        except psycopg.errors.ForeignKeyViolation as exc:
            raise PersistenceError(f"unknown job or revision for output ({job_id})") from exc
    return output_id


def trace_provenance(conn, *, output_id: uuid.UUID) -> dict[str, Any]:
    """Trace one output back to its immutable revision, job, chunks, and reviews.

    Every chunk/run/review/output row must resolve to exactly one immutable
    revision; this query is the audit proof of that invariant.
    """
    output = conn.execute(
        """
        SELECT o.output_id, o.job_id, o.revision_id, o.artifact_type,
               o.artifact_sha256,
               d.document_id, d.title,
               r.revision_no, r.source_sha256,
               j.status
        FROM chronicle.ingestion_outputs o
        JOIN chronicle.document_revisions r ON r.revision_id = o.revision_id
        JOIN chronicle.documents d ON d.document_id = r.document_id
        JOIN chronicle.ingestion_jobs j ON j.job_id = o.job_id
        WHERE o.output_id = %s
        """,
        (output_id,),
    ).fetchone()
    if output is None:
        raise PersistenceError(f"unknown output {output_id}")
    job_id = output[1]
    chunks = conn.execute(
        """
        SELECT c.chunk_id, c.chunk_index, c.section_id, c.status, c.attempt,
               (SELECT count(*) FROM chronicle.ingestion_chunk_runs r
                WHERE r.chunk_id = c.chunk_id) AS runs,
               (SELECT count(*) FROM chronicle.review_items v
                WHERE v.chunk_id = c.chunk_id) AS reviews
        FROM chronicle.ingestion_chunks c
        WHERE c.job_id = %s
        ORDER BY c.chunk_index
        """,
        (job_id,),
    ).fetchall()
    reviews = conn.execute(
        """
        SELECT review_id, kind, status, chunk_id
        FROM chronicle.review_items
        WHERE job_id = %s
        ORDER BY created_at
        """,
        (job_id,),
    ).fetchall()
    return {
        "output_id": str(output[0]),
        "job_id": str(output[1]),
        "revision_id": str(output[2]),
        "artifact_type": output[3],
        "artifact_sha256": output[4],
        "document_id": str(output[5]),
        "document_title": output[6],
        "revision_no": output[7],
        "revision_source_sha256": output[8],
        "job_status": output[9],
        "chunks": [
            {
                "chunk_id": str(row[0]),
                "chunk_index": row[1],
                "section_id": str(row[2]) if row[2] is not None else None,
                "status": row[3],
                "attempt": row[4],
                "runs": row[5],
                "reviews": row[6],
            }
            for row in chunks
        ],
        "reviews": [
            {
                "review_id": str(row[0]),
                "kind": row[1],
                "status": row[2],
                "chunk_id": str(row[3]) if row[3] is not None else None,
            }
            for row in reviews
        ],
    }
