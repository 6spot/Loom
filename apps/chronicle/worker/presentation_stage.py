"""C1-T12 offline Reader Presentation worker stage.

This module deliberately keeps model calls outside PostgreSQL transactions.
The frozen generation context is revalidated under the ingestion-job lease
immediately before the immutable projection and its control-plane output are
committed, so a stale worker cannot publish prose after cancellation/takeover.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg

import control_plane
import presentation
from common import PersistenceConflict, PersistenceError, sha256_json

STAGE_VERSION = "c1t12-present-v1"
ARTIFACT_TYPE = "reader-presentation"
_NO_DIRECT_CLAIMS = "has no direct evidenced Claims"


def _existing_for_input(
    conn,
    *,
    context: dict[str, Any],
    model_version: str,
) -> dict[str, Any] | None:
    """Find the latest exact-input artifact before another model call.

    This is crash-window adoption, not a general regeneration policy: manual
    or future explicit regeneration may still call ``persist_candidate`` with
    new output. The durable pipeline itself never spends another model call
    after it already committed this exact input/model/generator projection.
    """
    target_kind = context["target_kind"]
    column = "canonical_entity_id" if target_kind == "entity" else "canonical_event_id"
    row = conn.execute(
        f"""
        SELECT presentation_id, presentation_version, content_sha256
        FROM chronicle.reader_presentations
        WHERE target_kind = %s AND {column} = %s::uuid
          AND input_fingerprint = %s
          AND generator_version = %s AND prompt_version = %s
          AND model_version = %s AND status = 'published'
        ORDER BY presentation_version DESC
        LIMIT 1
        """,
        (
            target_kind,
            context["canonical_id"],
            context["input_fingerprint"],
            presentation.GENERATOR_VERSION,
            presentation.PROMPT_VERSION,
            model_version,
        ),
    ).fetchone()
    if row is None:
        return None
    return {
        "presentation_id": str(row[0]),
        "presentation_version": int(row[1]),
        "content_sha256": row[2],
        "input_fingerprint": context["input_fingerprint"],
        "adopted": True,
    }


def _record_output(
    conn,
    *,
    job_id: uuid.UUID,
    revision_id: uuid.UUID,
    stored: dict[str, Any],
    context: dict[str, Any],
    model_version: str,
) -> None:
    identity = {
        "artifact_type": ARTIFACT_TYPE,
        "presentation_id": stored["presentation_id"],
        "content_sha256": stored["content_sha256"],
    }
    control_plane.record_output(
        conn,
        job_id=job_id,
        revision_id=revision_id,
        artifact_type=ARTIFACT_TYPE,
        artifact_sha256=sha256_json(identity),
        payload={
            "presentation_id": stored["presentation_id"],
            "presentation_version": stored["presentation_version"],
            "target_kind": context["target_kind"],
            "canonical_id": context["canonical_id"],
            "language": presentation.BASE_LANGUAGE,
            "input_fingerprint": context["input_fingerprint"],
            "content_sha256": stored["content_sha256"],
            "generator_version": presentation.GENERATOR_VERSION,
            "prompt_version": presentation.PROMPT_VERSION,
            "model_version": model_version,
            "authoritative": False,
        },
    )


def execute_present_stage(
    database_url: str,
    *,
    job_id: uuid.UUID,
    worker: str,
    model: Any,
) -> dict[str, Any]:
    """Generate/persist all supported canonical targets touched by one job.

    Targets with no direct evidenced Claim are omitted, never filled with
    model/common knowledge. Any other grounding/validation error fails the
    stage. Every model call occurs with no database connection open.
    """
    if not callable(getattr(model, "complete", None)):
        raise PersistenceError("presentation_model must expose complete(prompt)->str")
    model_version = getattr(model, "name", None)
    if not isinstance(model_version, str) or not model_version:
        raise PersistenceError("presentation_model must expose a non-empty name")

    with psycopg.connect(database_url) as conn:
        targets = presentation.targets_for_job(conn, job_id=job_id)
        revision_row = conn.execute(
            "SELECT revision_id FROM chronicle.ingestion_jobs WHERE job_id = %s",
            (job_id,),
        ).fetchone()
        if revision_row is None:
            raise PersistenceError(f"unknown job {job_id}")
        revision_id = revision_row[0]

    report: dict[str, Any] = {
        "stage_version": STAGE_VERSION,
        "contract_version": presentation.CONTRACT_VERSION,
        "generator_version": presentation.GENERATOR_VERSION,
        "prompt_version": presentation.PROMPT_VERSION,
        "model_version": model_version,
        "targets": len(targets),
        "published": 0,
        "adopted": 0,
        "omitted_no_evidence": 0,
        "presentations": [],
        "authoritative": False,
    }

    for target in targets:
        try:
            with psycopg.connect(database_url) as conn:
                context = presentation.load_generation_context(
                    conn,
                    target_kind=target["target_kind"],
                    canonical_id=target["canonical_id"],
                )
                existing = _existing_for_input(
                    conn, context=context, model_version=model_version
                )
        except PersistenceError as exc:
            if _NO_DIRECT_CLAIMS in str(exc):
                report["omitted_no_evidence"] += 1
                continue
            raise

        if existing is None:
            # No connection is open across the model call.
            candidate = presentation.generate_candidate(context, model)
        else:
            candidate = None

        with psycopg.connect(database_url) as conn:
            with conn.transaction():
                control_plane.require_job_lease(
                    conn, job_id=job_id, worker=worker
                )
                # Re-read under the same transaction and reject a candidate
                # generated from a context that changed while the model ran.
                current = presentation.load_generation_context(
                    conn,
                    target_kind=target["target_kind"],
                    canonical_id=target["canonical_id"],
                )
                if current["input_fingerprint"] != context["input_fingerprint"]:
                    raise PersistenceConflict(
                        "Reader Presentation generation context changed during model call; "
                        "refusing to publish stale prose"
                    )
                if existing is None:
                    stored = presentation.persist_candidate(
                        conn,
                        context=context,
                        candidate=candidate,
                        model_version=model_version,
                        origin_job_id=job_id,
                    )
                else:
                    # Recheck after acquiring the lease: another legal worker
                    # may have committed the exact artifact after our read.
                    stored = _existing_for_input(
                        conn, context=context, model_version=model_version
                    )
                    if stored is None:
                        raise PersistenceConflict(
                            "Reader Presentation crash-window artifact vanished before adoption"
                        )
                _record_output(
                    conn,
                    job_id=job_id,
                    revision_id=revision_id,
                    stored=stored,
                    context=context,
                    model_version=model_version,
                )

        report["adopted" if stored.get("adopted") else "published"] += 1
        report["presentations"].append(
            {
                "presentation_id": stored["presentation_id"],
                "presentation_version": stored["presentation_version"],
                "target_kind": context["target_kind"],
                "canonical_id": context["canonical_id"],
                "input_fingerprint": context["input_fingerprint"],
                "content_sha256": stored["content_sha256"],
            }
        )

    return report
