"""Explicitly synthetic 5,000-unit/1,000-group scale fixture (C2-R2-T16).

The second-round acceptance requires a marked synthetic scale corpus to
measure windowing and direct locate at a size the real four-chapter corpus
does not reach. This module owns that synthetic-only fixture: it is a
standalone in-container script that seeds one synthetic reading stream through
the product persistence boundary (``canonical_store`` + ``reading_store``),
building the minimal chapter artifact/publication scaffolding the reading
store foreign keys require.

It is deliberately separate from ``second_round_gate.py``'s real-chain path so
the gate's "no direct product writes" guard still covers the real chain. Every
row produced here is labelled synthetic (``fixture:synthetic-scale`` warning
and ``synthetic`` manifest tag) and can never be cited as real content.
"""

from __future__ import annotations

SCALE_UNITS_ENV = "GATE_SCALE_UNITS"
SCALE_GROUPS_ENV = "GATE_SCALE_GROUPS"
SCALE_RESULT_MARKER = "GATE_SCALE_RESULT="

#: Python source executed inside the ``chronicle-worker`` container with
#: ``CHRONICLE_DATABASE_URL`` and the product modules already importable.
SEED_SCRIPT = r'''
import hashlib
import json
import os
import sys
import uuid

sys.path[:0] = [
    "apps/chronicle/persistence",
    "apps/chronicle/worker",
    "apps/chronicle/read_api",
]

import psycopg
from psycopg.types.json import Jsonb

import canonical_store
import control_plane
import reading_store

UNITS = int(os.environ.get("GATE_SCALE_UNITS", "5000"))
GROUPS = int(os.environ.get("GATE_SCALE_GROUPS", "1000"))
DATABASE_URL = os.environ["CHRONICLE_DATABASE_URL"]
WORKER = "scale-fixture"


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def uuid7():
    raw = bytearray(uuid.uuid4().bytes)
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(raw))


def unit_key(*parts):
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def build_units_and_groups(chapter_id, publication_id, artifact_sha256, total, groups):
    group_size = max(1, (total + groups - 1) // groups)
    units = []
    blocks = []
    for index in range(total):
        text = f"合成段落{index}。"
        blocks.append({"block_id": f"t_{index:05d}", "text": text})
        units.append(
            {
                "unit_id": "ru_" + unit_key("scale", str(publication_id), str(index))[:24],
                "ordinal": index,
                "publication_id": str(publication_id),
                "artifact_sha256": artifact_sha256,
                "chapter_id": chapter_id,
                "block_id": f"t_{index:05d}",
                "text_hash": sha(text),
                "narrative_time": {},
                "segments": [{"kind": "text", "text": text}],
                "context_entities": [],
                "source_anchor_ids": [f"anc_{index:05d}"],
                "group_id": "",
                "continues_previous": False,
            }
        )
    built_groups = []
    year = 200
    for group_index in range(0, total, group_size):
        last = min(total - 1, group_index + group_size - 1)
        group_id = "tg_" + unit_key("scale", str(group_index))[:16]
        narrative = {
            "mode": "events",
            "status": "resolved",
            "event_refs": [],
            "from_block_id": None,
            "observations": [],
            "year_key": f"gregorian:{year}",
            "period_key": f"gregorian:{year}",
            "year_label": f"{year}年",
            "period_label": "（月份未明确）",
            "precision": "year",
        }
        for ordinal in range(group_index, last + 1):
            unit = units[ordinal]
            unit["group_id"] = group_id
            unit["continues_previous"] = ordinal != group_index
            unit["narrative_time"] = {
                **narrative,
                "continues_previous": ordinal != group_index,
            }
        built_groups.append(
            {
                "ordinal": len(built_groups),
                "group_id": group_id,
                "first_unit_ordinal": group_index,
                "last_unit_ordinal": last,
                "first_unit_id": units[group_index]["unit_id"],
                "last_unit_id": units[last]["unit_id"],
                "unit_count": last - group_index + 1,
                "year_key": narrative["year_key"],
                "period_key": narrative["period_key"],
                "year_label": narrative["year_label"],
                "period_label": narrative["period_label"],
                "precision": narrative["precision"],
                "observations": [],
                "continues_previous": False,
            }
        )
        year += 1
    return units, built_groups, blocks


with psycopg.connect(DATABASE_URL) as conn:
    document_id = control_plane.create_document(conn, title="synthetic-scale")
    revision_id, _ = control_plane.create_revision(
        conn,
        document_id=document_id,
        source_sha256=sha("scale-source"),
        source_bytes=UNITS,
        source_media_type="text/markdown",
        filename="scale.md",
    )
    job_id = control_plane.queue_job(conn, revision_id=revision_id)
    control_plane.claim_job(conn, worker=WORKER, job_id=job_id, lease_seconds=3600)
    section_id = control_plane.create_section(
        conn, job_id=job_id, section_index=0, label="scale",
        source_start=0, source_end=UNITS,
    )
    chunk_id = control_plane.record_chunk(
        conn, job_id=job_id, section_id=section_id, chunk_index=0,
        source_start=0, source_end=UNITS,
        source_sha256=sha("scale-source"), content_sha256=sha("scale-chunk"),
    )
    control_plane.set_chunk_status(conn, chunk_id=chunk_id, status="running")
    run_id, _ = control_plane.record_chunk_run(
        conn, chunk_id=chunk_id, status="running", worker=WORKER
    )

    catalog = {
        "schema": "chronicle.canonical-catalog",
        "version": "0.1",
        "canonical_entities": [],
        "canonical_events": [],
        "event_relations": [],
        "warnings": [{"code": "fixture:synthetic-scale"}],
    }
    catalog_sha, _ = canonical_store.persist_catalog(conn, catalog)

    chapter_id = "ch_" + unit_key("scale-chapter")[:24]
    artifact_sha256 = sha("scale-artifact")
    conn.execute(
        """
        INSERT INTO chronicle.chapter_artifacts(
            artifact_sha256, job_id, revision_id, document_id, chapter_id,
            chapter_index, chunk_id, producing_run_id, request_fingerprint,
            candidate_sha256, payload
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            artifact_sha256, job_id, revision_id, document_id, chapter_id,
            0, chunk_id, run_id, sha("scale-fingerprint"), sha("scale-candidate"),
            Jsonb({"synthetic": True, "fixture": "synthetic-scale"}),
        ),
    )
    publication_id = uuid7()
    units, groups, blocks = build_units_and_groups(
        chapter_id, publication_id, artifact_sha256, UNITS, GROUPS
    )
    publication = {
        "schema": "chronicle.chapter-publication",
        "version": "0.1",
        "chapter_id": chapter_id,
        "chapter_index": 0,
        "revision_id": str(revision_id),
        "artifact_sha256": artifact_sha256,
        "catalog_sha256": catalog_sha,
        "assembled_bundle_sha256": sha("scale-assembled"),
        "translation_blocks": blocks,
    }
    conn.execute(
        """
        INSERT INTO chronicle.chapter_publications(
            publication_id, artifact_sha256, catalog_sha256,
            assembled_bundle_sha256, document_id, revision_id, job_id,
            chapter_id, payload
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            publication_id, artifact_sha256, catalog_sha, publication["assembled_bundle_sha256"],
            document_id, revision_id, job_id, chapter_id, Jsonb(publication),
        ),
    )

    full_text = "".join(
        "".join(segment["text"] for segment in unit["segments"]) for unit in units
    )
    manifest = {
        "schema": "chronicle.reading-stream-manifest",
        "version": "0.1",
        "tag": "synthetic-scale",
        "revision_id": str(revision_id),
        "catalog_sha": catalog_sha,
        "source_title": "synthetic-scale",
        "full_text_sha256": sha(full_text),
        "unit_count": len(units),
        "group_count": len(groups),
        "chapters": [
            {
                "chapter_id": chapter_id,
                "chapter_index": 0,
                "publication_id": str(publication_id),
                "artifact_sha256": artifact_sha256,
                "unit_count": len(units),
                "title": "synthetic-scale",
            }
        ],
    }
    stream = {
        "revision_id": str(revision_id),
        "document_id": str(document_id),
        "origin_catalog_sha": catalog_sha,
        "manifest": manifest,
        "chapter_publication_ids": [str(publication_id)],
        "units": units,
        "groups": groups,
        "event_occurrences": [],
    }
    stream_id = reading_store.persist_reading_stream(conn, stream)
    conn.commit()

    result = {
        "stream_id": str(stream_id),
        "catalog_sha": catalog_sha,
        "revision_id": str(revision_id),
        "unit_count": len(units),
        "group_count": len(groups),
        "first_unit_id": units[0]["unit_id"],
        "last_unit_id": units[-1]["unit_id"],
        "synthetic": True,
    }
    print("GATE_SCALE_RESULT=" + json.dumps(result, ensure_ascii=False))
'''


def parse_scale_result(stdout: str) -> dict:
    import json

    for line in reversed(stdout.splitlines()):
        if line.startswith(SCALE_RESULT_MARKER):
            return json.loads(line[len(SCALE_RESULT_MARKER):])
    raise RuntimeError("scale fixture produced no GATE_SCALE_RESULT marker")
