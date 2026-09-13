"""Studio projections and explicit new runs over the existing ingestion store.

No second queue or publication authority. Model selection is an immutable
ingestion output committed with the ordinary job; retry never rewrites it.
"""
from __future__ import annotations

import json
import uuid

import control_plane
from common import PersistenceConflict, PersistenceError, sha256_json

REQUEST_TYPE = "studio-production-request"
RESULT_TYPES = ("chapter-production-attempt", "chapter-production-step", "chapter-production-draft")


def read_request(conn, job_id):
    rows = conn.execute(
        "SELECT artifact_sha256, payload FROM chronicle.ingestion_outputs WHERE job_id = %s AND artifact_type = %s",
        (job_id, REQUEST_TYPE),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1 or sha256_json(rows[0][1]) != rows[0][0]:
        raise PersistenceConflict("production request changed")
    return rows[0][1]


def queue(conn, *, revision_id, max_attempts=8, selection=None, parent_job_id=None):
    with conn.transaction():
        if parent_job_id is not None:
            parent = conn.execute(
                "SELECT revision_id, status, checkpoint FROM chronicle.ingestion_jobs WHERE job_id = %s FOR UPDATE",
                (parent_job_id,),
            ).fetchone()
            if parent is None:
                raise PersistenceError("unknown parent job")
            if parent[0] != revision_id or parent[1] not in ("failed", "cancelled"):
                raise PersistenceConflict("only a failed or cancelled task can start a linked rerun")
            if (parent[2] or {}).get("narrative_scope"):
                raise PersistenceConflict("select published sources to create a new narrative task")
        job_id = control_plane.queue_job(conn, revision_id=revision_id, max_attempts=max_attempts)
        if selection is not None or parent_job_id is not None:
            value = {"version": "0.1", "model_selection": selection,
                     "parent_job_id": str(parent_job_id) if parent_job_id else None}
            control_plane.record_output(conn, job_id=job_id, revision_id=revision_id,
                artifact_type=REQUEST_TYPE, artifact_sha256=sha256_json(value), payload=value)
        return job_id


def enrich_jobs(conn, jobs):
    """Batch readable names and current state; never fetch one detail per row."""
    if not jobs:
        return jobs
    rows = conn.execute(
        """SELECT j.job_id, d.document_id, d.title, r.revision_no, r.filename,
                  j.checkpoint->'narrative_scope',
                  (SELECT count(*) FROM chronicle.review_items ri WHERE ri.job_id=j.job_id AND ri.status='open'),
                  (SELECT s.stage FROM chronicle.ingestion_job_stages s WHERE s.job_id=j.job_id
                   AND s.status IN ('running','needs_review','failed') ORDER BY s.started_at DESC NULLS LAST LIMIT 1)
           FROM chronicle.ingestion_jobs j
           JOIN chronicle.document_revisions r ON r.revision_id=j.revision_id
           JOIN chronicle.documents d ON d.document_id=r.document_id
           WHERE j.job_id=ANY(%s)""", ([uuid.UUID(job["job_id"]) for job in jobs],),
    ).fetchall()
    metadata = {}
    for job, document, title, revision, filename, scope, reviews, stage in rows:
        metadata[str(job)] = {"document": {"document_id": str(document), "title": title,
                              "revision_no": revision, "filename": filename},
                              "job_kind": "narrative" if scope else "chapter",
                              "source_count": len(scope.get("publication_ids", [])) if scope else 1,
                              "open_reviews": reviews, "current_stage": stage}
    return [{**job, **metadata.get(job["job_id"], {})} for job in jobs]


def enrich_detail(conn, detail):
    result = enrich_jobs(conn, [detail])[0]
    labels = dict(conn.execute(
        "SELECT section_id, label FROM chronicle.ingestion_sections WHERE job_id=%s", (detail["job_id"],),
    ).fetchall())
    for chunk in result["chunks"]:
        chunk["title"] = labels.get(uuid.UUID(chunk["section_id"])) if chunk.get("section_id") else None
    result["production_request"] = read_request(conn, detail["job_id"])
    # Explicit result metadata, with all attempts (not only the latest node
    # checkpoint). Large model bodies are read only when an operator opens one.
    rows = conn.execute(
        """SELECT artifact_sha256, payload->>'step', payload->>'model', payload->>'status',
                  payload->>'chunk_id', payload->'attempt', payload->'round'
           FROM chronicle.ingestion_outputs WHERE job_id=%s AND artifact_type=ANY(%s)
           ORDER BY created_at, output_id""", (detail["job_id"], list(RESULT_TYPES)),
    ).fetchall()
    by_digest = {row[0]: row for row in rows}
    for output in result["outputs"]:
        row = by_digest.get(output["artifact_sha256"])
        if row:
            output.update(dict(zip(("step", "model", "status", "chunk_id", "attempt", "round"), row[1:])))
            output["readable"] = True
    return result


def output_page(conn, *, job_id, digest, offset=0, limit=16000):
    if (isinstance(offset, bool) or not isinstance(offset, int) or offset < 0
            or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 16000):
        raise PersistenceError("invalid result page bounds")
    row = conn.execute(
        """SELECT o.artifact_type, o.payload FROM chronicle.ingestion_outputs o
           JOIN chronicle.ingestion_jobs j ON j.job_id=o.job_id AND j.revision_id=o.revision_id
           WHERE o.job_id=%s AND o.artifact_sha256=%s AND o.artifact_type=ANY(%s)""",
        (job_id, digest, list(RESULT_TYPES)),
    ).fetchone()
    if row is None:
        raise PersistenceError("unknown task result")
    kind, payload = row
    if not isinstance(payload, dict) or sha256_json(payload) != digest:
        raise PersistenceConflict("saved task result changed")
    # A positive allowlist: prompts, provider configuration, credentials,
    # inputs and unrecognized transport fields never reach the browser.
    safe = {key: payload[key] for key in ("step", "model", "status", "round", "attempt", "raw_text",
            "parsed", "candidate", "issues", "validation_errors", "error") if key in payload}
    text = json.dumps(safe, ensure_ascii=False, indent=2)
    if offset > len(text):
        raise PersistenceError("result page is outside the saved output")
    end = min(len(text), offset + limit)
    return {"job_id": str(job_id), "output_sha256": digest, "artifact_type": kind,
            "text": text[offset:end], "offset": offset, "total_chars": len(text),
            "next_offset": end if end < len(text) else None}
