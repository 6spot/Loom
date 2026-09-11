"""Chronicle C2-R1-T04 chapter artifact + publication store (application-owned).

Narrow persistence for complete natural-chapter joint products behind
``CHRONICLE_DATABASE_URL`` (Architecture Amendment 0006). Implements
``chapter-production.md`` sections 5/7:

- :func:`record_accepted_chapter_fenced` accepts only a fully validated
  ``chronicle.chapter-artifact / 0.1`` or ``/ 0.2`` (the T01 artifact is
  the sole accepted input) and commits the artifact row, the chunk
  accepted pointer, and the chunk ``completed`` status in one
  lease-fenced transaction. A 0.2 candidate is validated and accepted
  only through the T01 ``reading_contract`` (keeping its
  program-resolved reading annotations), a 0.1 candidate through the
  frozen first-round contract. Partial products, wrong revisions,
  unknown producing runs, lost leases, and hash conflicts are rejected;
  repeating the identical artifact is idempotent.
- :func:`read_accepted_chapters` / :func:`read_accepted_chapter` return
  already-accepted complete results so a restarted worker resumes from
  the accepted artifact instead of creating a second chapter queue/run.
- :func:`persist_chapter_publication` records one immutable public
  reading version per chapter; :func:`list_published_chapters` /
  :func:`read_published_chapter` expose only published chapters, so the
  public directory stays invisible until the publication helper runs.

The caller owns the connection; every mutating entry takes
``(conn, *, job_id, ..., worker, ...)`` and fences on the job lease via
:mod:`control_plane` inside a single short transaction. Model waits never
hold a database transaction. ``canonical_catalogs`` stays owned by
:mod:`canonical_store`; the unified catalog lock and write path belong to
T13. Resolution candidate rules belong to T08; this module never writes
resolution rows.

Boundary notes (Architecture Amendment 0006):

- This store uses only ``CHRONICLE_DATABASE_URL`` and only ``chronicle.*``
  chapter/control-plane tables. It never reads or writes Loom
  Runtime/World/Timeline/Work/Binding state and never imports
  ``loom-storage`` or ``PgStorage``.
- Chapters are processing/reference units inside one source-owned staged
  bundle. They never become historical identity boundaries; canonical
  identity remains owned by the C0 staged/resolution/canonical path.
"""

from __future__ import annotations

import secrets
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import chapter_contract as chapter_contract  # noqa: E402
import control_plane as control_plane  # noqa: E402
import reading_contract as reading_contract  # noqa: E402
from common import (  # noqa: E402
    LeaseLost,
    PersistenceConflict,
    PersistenceError,
    parse_uuid7,
    sha256_json,
)

#: Schema/version markers mirrored from the T01 contract. The store never
#: accepts any other artifact generation.
ARTIFACT_SCHEMA = chapter_contract.ARTIFACT_SCHEMA
ARTIFACT_VERSION = chapter_contract.ARTIFACT_VERSION


def _new_publication_id() -> uuid.UUID:
    """Generate an RFC 9562 UUIDv7 for one publication row."""
    unix_ms = time.time_ns() // 1_000_000
    if unix_ms >= 1 << 48:
        raise PersistenceError("current Unix millisecond timestamp does not fit UUIDv7")
    random_bits = secrets.randbits(74)
    value = (
        (unix_ms << 80)
        | (0x7 << 76)
        | ((random_bits >> 62) << 64)
        | (0b10 << 62)
        | (random_bits & ((1 << 62) - 1))
    )
    return uuid.UUID(int=value)


def _require_uuid(value: Any, description: str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PersistenceError(f"{description} must be a UUID, got {value!r}") from exc


def _job_row_for_update(conn, *, job_id: uuid.UUID) -> tuple[Any, ...]:
    row = conn.execute(
        """
        SELECT job_id, revision_id, status, lease_owner
        FROM chronicle.ingestion_jobs WHERE job_id = %s FOR UPDATE
        """,
        (job_id,),
    ).fetchone()
    if row is None:
        raise PersistenceError(f"unknown job {job_id}")
    return row


def record_accepted_chapter_fenced(
    conn,
    *,
    job_id: uuid.UUID,
    chunk_id: uuid.UUID,
    worker: str,
    request: dict[str, Any],
    candidate: dict[str, Any],
    producing_run: dict[str, Any],
) -> str:
    """Accept one complete chapter joint product under the job lease.

    The candidate is always re-validated against this exact request via
    the owning T01 contract (0.1 ``chapter_contract`` or 0.2
    ``reading_contract``); a caller-supplied report can never substitute
    for that check. On success the accepted artifact row, the chunk
    accepted pointer (``checkpoint.accepted_chapter_artifact``), and the
    chunk ``completed`` status commit atomically. Repeating the identical
    artifact returns its SHA without new rows; the same ``(job,
    chapter)`` with different content raises ``PersistenceConflict``
    (``immutable_artifact_conflict``).

    A producing run that already committed is adopted, never re-executed:
    its identity must resolve to this chunk, and the full
    request/candidate pair is still re-validated before anything is
    written.
    """
    job_id = _require_uuid(job_id, "job_id")
    chunk_id = _require_uuid(chunk_id, "chunk_id")
    if not isinstance(worker, str) or not worker:
        raise PersistenceError("worker must be a non-empty string")
    if not isinstance(request, dict) or not isinstance(candidate, dict):
        raise PersistenceError("chapter request and candidate must be JSON objects")
    if not isinstance(producing_run, dict):
        raise PersistenceError("producing_run must be a JSON object")
    run_id = producing_run.get("run_id")
    try:
        producing_run_id = run_id if isinstance(run_id, uuid.UUID) else uuid.UUID(str(run_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PersistenceError(f"producing_run run_id is not a UUID: {run_id!r}") from exc

    # Fail closed before touching the database: partial products, hash
    # drift, and chapter/request mismatches never reach a transaction. The
    # candidate generation selects its own owner: 0.1 stays with the frozen
    # first-round validator, 0.2 is consumed only through the T01
    # ``reading_contract`` validator so the accepted artifact keeps the
    # program-resolved reading annotations and unit IDs.
    accepted_run = {**producing_run, "run_id": str(producing_run_id)}
    candidate_version = candidate.get("version")
    if candidate_version == reading_contract.CANDIDATE_VERSION:
        artifact = reading_contract.accept_reading_candidate(
            request, candidate, producing_run=accepted_run
        )
    elif candidate_version == chapter_contract.CANDIDATE_VERSION:
        artifact = chapter_contract.accept_chapter_candidate(
            request, candidate, producing_run=accepted_run
        )
    else:
        raise PersistenceError(
            "chapter candidate version must be "
            f"{chapter_contract.CANDIDATE_VERSION!r} or "
            f"{reading_contract.CANDIDATE_VERSION!r}, got {candidate_version!r}"
        )
    if artifact.get("schema") != ARTIFACT_SCHEMA or artifact.get("version") not in (
        ARTIFACT_VERSION,
        reading_contract.ARTIFACT_VERSION,
    ):
        raise PersistenceError(
            "accepted artifact must be chronicle.chapter-artifact/0.1 or /0.2"
        )
    chapter_id = artifact["chapter_id"]
    if not isinstance(chapter_id, str) or not chapter_id:
        raise PersistenceError("accepted artifact chapter_id must be a non-empty string")
    request_fingerprint = artifact["request_fingerprint"]
    candidate_sha256 = artifact["candidate_sha256"]
    artifact_sha256 = sha256_json(artifact)

    with conn.transaction():
        # Lease fence first: cancelled jobs and taken-over leases hold no
        # lease for this worker, so stale execution halts here.
        control_plane.require_job_lease(conn, job_id=job_id, worker=worker)

        _job_id, job_revision_id, job_status, _lease_owner = _job_row_for_update(
            conn, job_id=job_id
        )
        if job_status in ("cancelled", "failed", "completed"):
            raise PersistenceConflict(
                f"job {job_id} is {job_status!r}; accepted chapters cannot be recorded"
            )
        if str(job_revision_id) != str(request.get("revision_id")):
            raise PersistenceConflict(
                f"chapter request revision {request.get('revision_id')!r} does not match "
                f"revision {job_revision_id} of job {job_id}"
            )
        revision_row = conn.execute(
            "SELECT document_id FROM chronicle.document_revisions WHERE revision_id = %s",
            (job_revision_id,),
        ).fetchone()
        if revision_row is None:  # pragma: no cover - FK guards this
            raise PersistenceError(f"unknown revision {job_revision_id}")
        document_id = revision_row[0]

        chunk_row = conn.execute(
            """
            SELECT job_id, status, checkpoint
            FROM chronicle.ingestion_chunks WHERE chunk_id = %s FOR UPDATE
            """,
            (chunk_id,),
        ).fetchone()
        if chunk_row is None:
            raise PersistenceError(f"unknown chunk {chunk_id}")
        if chunk_row[0] != job_id:
            raise PersistenceConflict(
                f"chunk {chunk_id} belongs to job {chunk_row[0]}, not job {job_id}"
            )
        chunk_status = chunk_row[1]

        run_row = conn.execute(
            """
            SELECT chunk_id, worker, checkpoint, status
            FROM chronicle.ingestion_chunk_runs WHERE run_id = %s
            """,
            (producing_run_id,),
        ).fetchone()
        if run_row is None:
            raise PersistenceConflict(
                f"producing run {producing_run_id} is not persisted; "
                "record the chunk run before accepting its chapter"
            )
        if run_row[0] != chunk_id:
            raise PersistenceConflict(
                f"producing run {producing_run_id} belongs to chunk {run_row[0]}, "
                f"not chunk {chunk_id}"
            )
        if run_row[3] not in ("running", "completed"):
            raise PersistenceConflict(
                f"producing run {producing_run_id} is {run_row[3]!r}; "
                "a failed run can never produce an accepted chapter"
            )
        run_checkpoint = run_row[2] or {}
        if isinstance(run_checkpoint, dict) and run_checkpoint.get("request_fingerprint") not in (
            None,
            request_fingerprint,
        ):
            raise PersistenceConflict(
                f"producing run {producing_run_id} fingerprint "
                f"{run_checkpoint.get('request_fingerprint')!r} does not match "
                f"chapter request fingerprint {request_fingerprint!r} (hash drift)"
            )

        # Idempotency: the same (job, chapter) key with the same bytes is
        # a replay; with different bytes it is an immutability conflict.
        existing = conn.execute(
            """
            SELECT artifact_sha256, payload
            FROM chronicle.chapter_artifacts WHERE job_id = %s AND chapter_id = %s
            """,
            (job_id, chapter_id),
        ).fetchone()
        if existing is not None:
            if existing[0] != artifact_sha256:
                raise PersistenceConflict(
                    f"immutable_artifact_conflict: chapter {chapter_id!r} of job {job_id} "
                    f"already accepted as {existing[0]}, refusing {artifact_sha256}"
                )
            if existing[1] != artifact:
                raise PersistenceConflict(
                    f"chapter artifact hash collision/conflict {artifact_sha256}"
                )
            _point_chunk_at_artifact(conn, chunk_id=chunk_id, artifact_sha256=artifact_sha256,
                                     request_fingerprint=request_fingerprint,
                                     chunk_status=chunk_status)
            return artifact_sha256

        try:
            # The race insert runs in its own savepoint: a concurrent
            # identical accept rolls back only to the savepoint, so the
            # fenced transaction stays usable for the idempotent re-read
            # below instead of dying with InFailedSqlTransaction.
            with conn.transaction(savepoint_name="chapter_artifact_insert"):
                conn.execute(
                    """
                    INSERT INTO chronicle.chapter_artifacts(
                        artifact_sha256, job_id, revision_id, document_id,
                        chapter_id, chapter_index, chunk_id, producing_run_id,
                        request_fingerprint, candidate_sha256, payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        artifact_sha256,
                        job_id,
                        job_revision_id,
                        document_id,
                        chapter_id,
                        int(request.get("chapter_index", 0)),
                        chunk_id,
                        producing_run_id,
                        request_fingerprint,
                        candidate_sha256,
                        Jsonb(artifact),
                    ),
                )
        except Exception as exc:
            from psycopg import errors as _errors

            if isinstance(exc, _errors.UniqueViolation):
                # Lost race with a concurrent identical accept: re-read
                # under the same fence instead of reporting a conflict.
                row = conn.execute(
                    "SELECT artifact_sha256, payload FROM chronicle.chapter_artifacts"
                    " WHERE job_id = %s AND chapter_id = %s",
                    (job_id, chapter_id),
                ).fetchone()
                if (
                    row is not None
                    and row[0] == artifact_sha256
                    and row[1] == artifact
                ):
                    _point_chunk_at_artifact(
                        conn, chunk_id=chunk_id, artifact_sha256=artifact_sha256,
                        request_fingerprint=request_fingerprint,
                        chunk_status=conn.execute(
                            "SELECT status FROM chronicle.ingestion_chunks WHERE chunk_id = %s",
                            (chunk_id,),
                        ).fetchone()[0],
                    )
                    return artifact_sha256
                raise PersistenceConflict(
                    f"chapter artifact {artifact_sha256} conflicts with a persisted row"
                ) from exc
            raise

        if chunk_status not in ("running", "completed"):
            raise PersistenceConflict(
                f"chunk {chunk_id} is {chunk_status!r}; move it to 'running' "
                "before accepting its chapter (the accept step completes it)"
            )
        _point_chunk_at_artifact(conn, chunk_id=chunk_id, artifact_sha256=artifact_sha256,
                                 request_fingerprint=request_fingerprint,
                                 chunk_status=chunk_status)
    return artifact_sha256


def _point_chunk_at_artifact(
    conn, *, chunk_id: uuid.UUID, artifact_sha256: str,
    request_fingerprint: str, chunk_status: str,
) -> None:
    """Point a chunk at its accepted artifact and complete it (idempotent)."""
    from datetime import datetime, timezone

    if chunk_status == "completed":
        row = conn.execute(
            "SELECT checkpoint FROM chronicle.ingestion_chunks WHERE chunk_id = %s",
            (chunk_id,),
        ).fetchone()
        checkpoint = row[0] if row and isinstance(row[0], dict) else {}
        if checkpoint.get("accepted_chapter_artifact") not in (None, artifact_sha256):
            raise PersistenceConflict(
                f"chunk {chunk_id} already accepted a different chapter artifact "
                f"{checkpoint.get('accepted_chapter_artifact')!r}"
            )
    conn.execute(
        """
        UPDATE chronicle.ingestion_chunks
        SET status = 'completed',
            checkpoint = COALESCE(checkpoint, '{}'::jsonb)
                || jsonb_build_object(
                    'accepted_chapter_artifact', %s::text,
                    'request_fingerprint', %s::text
                ),
            updated_at = %s
        WHERE chunk_id = %s
        """,
        (
            artifact_sha256,
            request_fingerprint,
            datetime.now(timezone.utc),
            chunk_id,
        ),
    )


def read_accepted_chapters(conn, *, job_id: uuid.UUID) -> list[dict[str, Any]]:
    """Return every accepted chapter artifact payload for a job, in order.

    Read-only: no lease is required, so an interrupted worker resumes by
    reading these complete results without re-running the model or
    creating another chapter queue/run.
    """
    job_id = _require_uuid(job_id, "job_id")
    rows = conn.execute(
        """
        SELECT artifact_sha256, chapter_id, chapter_index, request_fingerprint,
               candidate_sha256, chunk_id, producing_run_id, payload
        FROM chronicle.chapter_artifacts
        WHERE job_id = %s
        ORDER BY chapter_index, chapter_id
        """,
        (job_id,),
    ).fetchall()
    return [
        {
            "artifact_sha256": row[0],
            "chapter_id": row[1],
            "chapter_index": int(row[2]),
            "request_fingerprint": row[3],
            "candidate_sha256": row[4],
            "chunk_id": str(row[5]),
            "producing_run_id": str(row[6]),
            "artifact": row[7],
        }
        for row in rows
    ]


def read_accepted_chapter(
    conn, *, job_id: uuid.UUID, chapter_id: str
) -> dict[str, Any] | None:
    """Return one accepted chapter entry, or None when not yet accepted."""
    job_id = _require_uuid(job_id, "job_id")
    if not isinstance(chapter_id, str) or not chapter_id:
        raise PersistenceError("chapter_id must be a non-empty string")
    row = conn.execute(
        """
        SELECT artifact_sha256, chapter_index, request_fingerprint,
               candidate_sha256, chunk_id, producing_run_id, payload
        FROM chronicle.chapter_artifacts
        WHERE job_id = %s AND chapter_id = %s
        """,
        (job_id, chapter_id),
    ).fetchone()
    if row is None:
        return None
    return {
        "artifact_sha256": row[0],
        "chapter_id": chapter_id,
        "chapter_index": int(row[1]),
        "request_fingerprint": row[2],
        "candidate_sha256": row[3],
        "chunk_id": str(row[4]),
        "producing_run_id": str(row[5]),
        "artifact": row[6],
    }


def insert_chapter_publication_in_txn(
    conn,
    *,
    job_id: uuid.UUID,
    artifact_sha256: str,
    catalog_sha256: str,
    assembled_bundle_sha256: str,
    publication: dict[str, Any],
) -> uuid.UUID:
    """Insert one chapter publication inside the caller's transaction.

    Assumes the caller already holds the transaction (and, for worker
    writes, the job lease plus the unified publish advisory lock): no
    transaction is opened here so the atomic T13 publish can commit the
    catalog, every chapter publication, and the publish checkpoint
    together. The same ``(artifact, catalog, assembled-bundle)`` triple
    with identical bytes is idempotent; different bytes raise
    ``PersistenceConflict``.
    """
    import re

    job_id = _require_uuid(job_id, "job_id")
    sha_re = re.compile(r"^[0-9a-f]{64}$")
    for value, description in (
        (artifact_sha256, "artifact_sha256"),
        (catalog_sha256, "catalog_sha256"),
        (assembled_bundle_sha256, "assembled_bundle_sha256"),
    ):
        if not isinstance(value, str) or not sha_re.match(value):
            raise PersistenceError(f"{description} must be a lowercase hex SHA-256 string")
    if not isinstance(publication, dict):
        raise PersistenceError("publication payload must be a JSON object")

    artifact_row = conn.execute(
        """
        SELECT job_id, revision_id, document_id, chapter_id, payload
        FROM chronicle.chapter_artifacts WHERE artifact_sha256 = %s
        """,
        (artifact_sha256,),
    ).fetchone()
    if artifact_row is None:
        raise PersistenceConflict(
            f"chapter artifact {artifact_sha256} is not accepted; "
            "publish only accepted chapters"
        )
    if artifact_row[0] != job_id:
        raise PersistenceConflict(
            f"chapter artifact {artifact_sha256} belongs to job {artifact_row[0]}, "
            f"not job {job_id}"
        )
    if (
        isinstance(publication.get("chapter_id"), str)
        and publication["chapter_id"] != artifact_row[3]
    ):
        raise PersistenceConflict(
            f"publication chapter {publication['chapter_id']!r} does not match "
            f"artifact chapter {artifact_row[3]!r}"
        )

    existing = conn.execute(
        """
        SELECT publication_id, payload
        FROM chronicle.chapter_publications
        WHERE artifact_sha256 = %s AND catalog_sha256 = %s
          AND assembled_bundle_sha256 = %s
        """,
        (artifact_sha256, catalog_sha256, assembled_bundle_sha256),
    ).fetchone()
    if existing is not None:
        if existing[1] != publication:
            raise PersistenceConflict(
                f"chapter publication for artifact {artifact_sha256} conflicts: "
                "same (artifact, catalog, bundle) triple carries different bytes"
            )
        return existing[0]

    publication_id = _new_publication_id()
    try:
        # As above, the race insert is savepoint-scoped so a
        # concurrent identical publication stays idempotent instead
        # of aborting the fenced transaction.
        with conn.transaction(savepoint_name="chapter_publication_insert"):
            conn.execute(
                """
                INSERT INTO chronicle.chapter_publications(
                    publication_id, artifact_sha256, catalog_sha256,
                    assembled_bundle_sha256, document_id, revision_id, job_id,
                    chapter_id, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    publication_id,
                    artifact_sha256,
                    catalog_sha256,
                    assembled_bundle_sha256,
                    artifact_row[2],
                    artifact_row[1],
                    job_id,
                    artifact_row[3],
                    Jsonb(publication),
                ),
            )
    except Exception as exc:
        from psycopg import errors as _errors

        if isinstance(exc, _errors.UniqueViolation):
            row = conn.execute(
                """
                SELECT publication_id, payload
                FROM chronicle.chapter_publications
                WHERE artifact_sha256 = %s AND catalog_sha256 = %s
                  AND assembled_bundle_sha256 = %s
                """,
                (artifact_sha256, catalog_sha256, assembled_bundle_sha256),
            ).fetchone()
            if row is not None and row[1] == publication:
                return row[0]
            raise PersistenceConflict(
                f"chapter publication for artifact {artifact_sha256} conflicts"
            ) from exc
        raise
    parse_uuid7(str(publication_id), "publication_id")
    return publication_id


def persist_chapter_publication(
    conn,
    *,
    job_id: uuid.UUID,
    worker: str,
    artifact_sha256: str,
    catalog_sha256: str,
    assembled_bundle_sha256: str,
    publication: dict[str, Any],
) -> uuid.UUID:
    """Record one immutable public reading version for an accepted chapter.

    The same ``(artifact, catalog, assembled-bundle)`` triple with
    identical bytes is idempotent and returns the existing
    ``publication_id``; the same triple with different bytes raises
    ``PersistenceConflict``. This helper performs no worker wiring: the
    atomic multi-chapter publish transaction belongs to T13.
    """
    job_id = _require_uuid(job_id, "job_id")
    if not isinstance(worker, str) or not worker:
        raise PersistenceError("worker must be a non-empty string")
    if not isinstance(publication, dict):
        raise PersistenceError("publication payload must be a JSON object")

    with conn.transaction():
        control_plane.require_job_lease(conn, job_id=job_id, worker=worker)
        return insert_chapter_publication_in_txn(
            conn, job_id=job_id, artifact_sha256=artifact_sha256,
            catalog_sha256=catalog_sha256,
            assembled_bundle_sha256=assembled_bundle_sha256,
            publication=publication,
        )


def list_published_chapters(
    conn,
    *,
    job_id: uuid.UUID | None = None,
    revision_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List published chapter directory entries (public visibility gate).

    Only chapters recorded through :func:`persist_chapter_publication`
    appear here; accepted-but-unpublished chapters stay invisible. All
    parameters are optional filters; results order by
    ``(published_at, publication_id)`` for a stable directory cursor.
    """
    if not isinstance(limit, int) or limit < 1 or limit > 100:
        raise PersistenceError("limit must be an integer between 1 and 100")
    if not isinstance(offset, int) or offset < 0:
        raise PersistenceError("offset must be a non-negative integer")
    clauses = []
    params: list[Any] = []
    if job_id is not None:
        clauses.append("p.job_id = %s")
        params.append(_require_uuid(job_id, "job_id"))
    if revision_id is not None:
        clauses.append("p.revision_id = %s")
        params.append(_require_uuid(revision_id, "revision_id"))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT p.publication_id, p.artifact_sha256, p.catalog_sha256,
               p.assembled_bundle_sha256, p.document_id, p.revision_id,
               p.job_id, p.chapter_id, a.chapter_index, p.published_at
        FROM chronicle.chapter_publications p
        JOIN chronicle.chapter_artifacts a
          ON a.artifact_sha256 = p.artifact_sha256
        {where}
        ORDER BY p.published_at, p.publication_id
        LIMIT %s OFFSET %s
        """,
        (*params, limit, offset),
    ).fetchall()
    return [
        {
            "publication_id": str(row[0]),
            "artifact_sha256": row[1],
            "catalog_sha256": row[2],
            "assembled_bundle_sha256": row[3],
            "document_id": str(row[4]),
            "revision_id": str(row[5]),
            "job_id": str(row[6]),
            "chapter_id": row[7],
            "chapter_index": int(row[8]),
            "published_at": row[9].isoformat() if row[9] is not None else None,
        }
        for row in rows
    ]


def read_published_chapter(conn, *, publication_id: uuid.UUID) -> dict[str, Any]:
    """Return one published chapter (artifact + publication payloads).

    Raises :class:`PersistenceError` for unknown publications: unpublished
    anchors, cross-publication anchors, and unknown versions are never
    silently served from another chapter.
    """
    publication_id = _require_uuid(publication_id, "publication_id")
    row = conn.execute(
        """
        SELECT p.publication_id, p.artifact_sha256, p.catalog_sha256,
               p.assembled_bundle_sha256, p.document_id, p.revision_id,
               p.job_id, p.chapter_id, a.chapter_index,
               a.payload, p.payload, p.published_at
        FROM chronicle.chapter_publications p
        JOIN chronicle.chapter_artifacts a
          ON a.artifact_sha256 = p.artifact_sha256
        WHERE p.publication_id = %s
        """,
        (publication_id,),
    ).fetchone()
    if row is None:
        raise PersistenceError(f"unknown publication {publication_id}")
    return {
        "publication_id": str(row[0]),
        "artifact_sha256": row[1],
        "catalog_sha256": row[2],
        "assembled_bundle_sha256": row[3],
        "document_id": str(row[4]),
        "revision_id": str(row[5]),
        "job_id": str(row[6]),
        "chapter_id": row[7],
        "chapter_index": int(row[8]),
        "artifact": row[9],
        "publication": row[10],
        "published_at": row[11].isoformat() if row[11] is not None else None,
    }
