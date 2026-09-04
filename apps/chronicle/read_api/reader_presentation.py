"""Read-only projection of the latest published C1-T12 Reader Presentation."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from read_common import ReadModelError


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ReadModelError("canonical presentation target must be a UUID") from exc


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def latest_reader_presentation(conn, *, target_kind: str, canonical_id: str) -> dict[str, Any] | None:
    if target_kind not in {"entity", "event"}:
        raise ReadModelError("Reader Presentation target_kind must be entity or event")
    target = _uuid(canonical_id)
    column = "canonical_entity_id" if target_kind == "entity" else "canonical_event_id"
    row = conn.execute(
        f"""
        SELECT presentation_id, base_language, contract_version,
               presentation_version, status,
               generator_version, model_version, prompt_version,
               input_fingerprint, content_sha256,
               origin_job_id, supersedes_presentation_id, generated_at
        FROM chronicle.reader_presentations
        WHERE target_kind = %s AND {column} = %s AND status = 'published'
        ORDER BY presentation_version DESC
        LIMIT 1
        """,
        (target_kind, target),
    ).fetchone()
    if row is None:
        return None
    presentation_id = row[0]
    block_rows = conn.execute(
        """
        SELECT block_index, block_id, block_kind, epistemic_mode, text
        FROM chronicle.reader_presentation_blocks
        WHERE presentation_id = %s
        ORDER BY block_index
        """,
        (presentation_id,),
    ).fetchall()
    support_rows = conn.execute(
        """
        SELECT s.block_index, s.bundle_label, s.claim_ref,
               c.payload, b.source_title, b.source_ref
        FROM chronicle.reader_presentation_supports s
        JOIN chronicle.staged_claims c
          ON c.bundle_label = s.bundle_label AND c.record_ref = s.claim_ref
        JOIN chronicle.source_bundles b ON b.bundle_label = s.bundle_label
        WHERE s.presentation_id = %s
        ORDER BY s.block_index, s.bundle_label, s.claim_ref
        """,
        (presentation_id,),
    ).fetchall()
    supports: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for block_index, bundle, claim_ref, claim, source_title, source_ref in support_rows:
        supports[int(block_index)].append(
            {
                "bundle": bundle,
                "ref": claim_ref,
                "claim": claim,
                "source": {"title": source_title, "ref": source_ref},
            }
        )
    return {
        "presentation_id": str(presentation_id),
        "target_kind": target_kind,
        "canonical_id": str(target),
        "language": row[1],
        "contract_version": row[2],
        "presentation_version": int(row[3]),
        "status": row[4],
        "generator": {
            "generator_version": row[5],
            "model_version": row[6],
            "prompt_version": row[7],
        },
        "input_fingerprint": row[8],
        "content_sha256": row[9],
        "origin_job_id": str(row[10]) if row[10] is not None else None,
        "supersedes_presentation_id": str(row[11]) if row[11] is not None else None,
        "generated_at": _iso(row[12]),
        "blocks": [
            {
                "block_id": block_id,
                "block_kind": block_kind,
                "epistemic_mode": epistemic_mode,
                "text": text,
                "supports": supports.get(int(block_index), []),
            }
            for block_index, block_id, block_kind, epistemic_mode, text in block_rows
        ],
    }
