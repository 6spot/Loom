"""Explicitly synthetic 5,000-unit/1,000-group scale fixture (C2-R2-T16).

The second-round acceptance requires a marked synthetic scale corpus to measure
windowing and direct locate at a size the real four-chapter corpus does not
reach. This module owns that synthetic-only fixture: a standalone in-container
script that drives the product persistence boundary for one tiny synthetic
chapter (``chapter_store.record_accepted_chapter_fenced`` +
``chapter_store.persist_chapter_publication``) and then persists a
5,000-unit/1,000-group stream through the product
``reading_store.persist_reading_stream`` entry.

No product row is written with raw SQL by the gate, and every unit cites a
block that exists in the referenced published chapter publication. All units
and groups are contract-complete (``narrative_time`` unknown-mode with empty
``event_refs``, valid ``context_entity_view`` entries) and the stream is
labelled synthetic in its manifest (``synthetic-scale`` tag) so it can never be
cited as real content.

The module is separate from ``second_round_gate.py``'s real-chain path so the
gate's "no direct product writes" guard still covers the real chain.
"""

from __future__ import annotations

SCALE_UNITS_ENV = "GATE_SCALE_UNITS"
SCALE_GROUPS_ENV = "GATE_SCALE_GROUPS"
SCALE_RESULT_MARKER = "GATE_SCALE_RESULT="
SCALE_UNITS_PLACEHOLDER = "__GATE_SCALE_UNITS__"
SCALE_GROUPS_PLACEHOLDER = "__GATE_SCALE_GROUPS__"

#: Python source executed inside the ``chronicle-worker`` container with
#: ``CHRONICLE_DATABASE_URL`` and the product modules already importable.
SEED_SCRIPT = r'''
import hashlib
import json
import sys
import uuid

sys.path[:0] = [
    "apps/chronicle/persistence",
    "apps/chronicle/worker",
    "apps/chronicle/read_api",
]

import canonical_store
import chapter_contract
import chapter_plan
import chapter_store
import control_plane
import fixture_model
import reading_store

UNITS = int("__GATE_SCALE_UNITS__")
GROUPS = int("__GATE_SCALE_GROUPS__")
WORKER = "scale-fixture"
TEXT = "".join(f"合成段落{index}。" for index in range(40))


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def uuid7():
    raw = bytearray(uuid.uuid4().bytes)
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(raw))


def unit_key(*parts):
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def pick_mention(text, blocked):
    for length in (6, 8, 10, 12):
        step = max(1, length // 2)
        for start in range(0, max(0, len(text) - length), step):
            snippet = text[start:start + length]
            if not snippet.strip() or "\n" in snippet or "#" in snippet:
                continue
            if snippet in blocked:
                continue
            if text.count(snippet) == 1:
                return snippet
    raise SystemExit("scale seed: no unique mention")


def unknown_time(continues):
    return {
        "mode": "unknown",
        "status": "unknown",
        "event_refs": [],
        "from_block_id": None,
        "observations": [],
        "year_key": "unknown",
        "period_key": "unknown",
        "year_label": None,
        "period_label": "时间未明确",
        "precision": "unknown",
        "continues_previous": continues,
    }


import psycopg

database_url = __import__("os").environ["CHRONICLE_DATABASE_URL"]

with psycopg.connect(database_url) as conn:
    document_id = control_plane.create_document(conn, title="synthetic-scale")
    revision_id, _ = control_plane.create_revision(
        conn,
        document_id=document_id,
        source_sha256=sha(TEXT),
        source_bytes=len(TEXT.encode("utf-8")),
        source_media_type="text/plain",
        filename="scale.txt",
    )
    job_id = control_plane.queue_job(conn, revision_id=revision_id)
    control_plane.claim_job(conn, worker=WORKER, job_id=job_id, lease_seconds=3600)
    section_id = control_plane.create_section(
        conn, job_id=job_id, section_index=0, label="scale",
        source_start=0, source_end=len(TEXT),
    )
    chunk_id = control_plane.record_chunk(
        conn, job_id=job_id, section_id=section_id, chunk_index=0,
        source_start=0, source_end=len(TEXT),
        source_sha256=sha(TEXT), content_sha256=sha("scale-chunk"),
    )
    control_plane.set_chunk_status(conn, chunk_id=chunk_id, status="running")
    run_id, _ = control_plane.record_chunk_run(
        conn, chunk_id=chunk_id, status="running", worker=WORKER
    )

    limits = chapter_contract.ChapterLimits()
    locator = {
        "revision_id": str(revision_id),
        "source_sha256": sha(TEXT),
        "normalized_sha256": sha(TEXT),
    }
    plan = chapter_plan.plan_chapters(TEXT, locator, "scale.txt", limits=limits)
    request = chapter_plan.build_chapter_request(plan, 0, TEXT, limits=limits)
    request["normalized_sha256"] = sha(request["normalized_text"])
    mention = pick_mention(request["normalized_text"], set())
    spec = {
        "chapter_id": request["chapter_id"],
        "revision_id": request["revision_id"],
        "source_title": "synthetic-scale",
        "translation_text": f"合成譯文（{mention}）",
        "entities": [{"mention": mention, "type": "person", "name": mention}],
        "event": {"type": "battle", "title": "合成事件"},
        "predicate": "affected",
    }
    candidate = fixture_model.build_reading_chapter_candidate(request, spec)
    producing_run = {
        "run_id": str(run_id),
        "model": "fixture:c2r2-scale:reading-chapter",
        "prompt_schema_version": "c2r2-scale",
    }
    artifact_sha256 = chapter_store.record_accepted_chapter_fenced(
        conn, job_id=job_id, chunk_id=chunk_id, worker=WORKER,
        request=request, candidate=candidate, producing_run=producing_run,
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

    blocks = request["blocks"]
    block_id = blocks[0]["block_id"]
    block_text = request["normalized_text"][blocks[0]["start"]:blocks[0]["end"]]
    chapter_id = request["chapter_id"]
    assembled_sha = sha("scale-assembled")
    publication = {
        "schema": "chronicle.chapter-publication",
        "version": "0.1",
        "chapter_id": chapter_id,
        "chapter_index": 0,
        "revision_id": str(revision_id),
        "artifact_sha256": artifact_sha256,
        "catalog_sha256": catalog_sha,
        "assembled_bundle_sha256": assembled_sha,
        "translation_blocks": [{"block_id": block_id, "text": block_text}],
    }
    publication_id = chapter_store.persist_chapter_publication(
        conn,
        job_id=job_id,
        worker=WORKER,
        artifact_sha256=artifact_sha256,
        catalog_sha256=catalog_sha,
        assembled_bundle_sha256=assembled_sha,
        publication=publication,
    )

    group_size = max(1, (UNITS + GROUPS - 1) // GROUPS)
    units = []
    for index in range(UNITS):
        context_entities = []
        if index % 10 == 0:
            context_entities.append(
                {
                    "entity_ref": "scale_ent_1",
                    "name": "合成人物",
                    "canonical_id": None,
                    "kind": "person",
                    "importance": "primary",
                    "source_anchor_ids": [],
                    "event_roles": [],
                }
            )
        units.append(
            {
                "unit_id": "ru_" + unit_key("scale", str(publication_id), str(index))[:24],
                "ordinal": index,
                "publication_id": str(publication_id),
                "artifact_sha256": artifact_sha256,
                "chapter_id": chapter_id,
                "block_id": block_id,
                "text_hash": sha(block_text),
                "narrative_time": unknown_time(False),
                "segments": [{"kind": "text", "text": block_text}],
                "context_entities": context_entities,
                "source_anchor_ids": [],
                "group_id": "",
                "continues_previous": False,
            }
        )
    built_groups = []
    for start in range(0, UNITS, group_size):
        last = min(UNITS - 1, start + group_size - 1)
        group_id = "tg_" + unit_key("scale", str(start))[:16]
        for ordinal in range(start, last + 1):
            units[ordinal]["group_id"] = group_id
            units[ordinal]["continues_previous"] = ordinal != start
            units[ordinal]["narrative_time"] = unknown_time(ordinal != start)
        built_groups.append(
            {
                "ordinal": len(built_groups),
                "group_id": group_id,
                "first_unit_ordinal": start,
                "last_unit_ordinal": last,
                "first_unit_id": units[start]["unit_id"],
                "last_unit_id": units[last]["unit_id"],
                "unit_count": last - start + 1,
                "year_key": "unknown",
                "period_key": "unknown",
                "year_label": None,
                "period_label": "时间未明确",
                "precision": "unknown",
                "observations": [],
                "continues_previous": False,
            }
        )

    full_text = "".join(unit["segments"][0]["text"] for unit in units)
    manifest = {
        "schema": "chronicle.reading-stream-manifest",
        "version": "0.1",
        "tag": "synthetic-scale",
        "revision_id": str(revision_id),
        "catalog_sha": catalog_sha,
        "source_title": "synthetic-scale",
        "full_text_sha256": sha(full_text),
        "unit_count": len(units),
        "group_count": len(built_groups),
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
        "groups": built_groups,
        "event_occurrences": [],
    }
    with conn.transaction():
        stream_id = reading_store.persist_reading_stream(conn, stream)
    conn.commit()

    result = {
        "stream_id": str(stream_id),
        "catalog_sha": catalog_sha,
        "revision_id": str(revision_id),
        "publication_id": str(publication_id),
        "unit_count": len(units),
        "group_count": len(built_groups),
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
