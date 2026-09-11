"""PostgreSQL 18 tests for the C2-R2-T08 event preview / target lookup.

Covers ``continuous-reading.md`` §5-7 with real published reading streams:
snapshot identity is the immutable catalog payload plus the stream's origin
catalog sequence, so a later member can never leak into an older card, a
same-named event never crosses to another canonical id, a retrospective
mention never masquerades as an occurrence paragraph, targets page with a
stable keyset cursor and never let a first page impersonate the whole set,
and a cursor is bound to its snapshot.

The seed path inserts control-plane/document rows directly (an explicit test
loading path, exactly like the T05 store fixture); the production write path
is T06's single publish transaction.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PERSISTENCE = ROOT / "apps/chronicle/persistence"
for path in (PERSISTENCE, HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import canonical_store
import control_plane
import reading_store
from migrations import apply_migrations
from read_common import ReadModelError, ReadModelNotFound
from reading_events import ReadModelInconsistency, event_preview, event_targets


DEFAULT_CONTROL_URL = "postgresql://loom:loom@127.0.0.1:15432/loom_control"

_UUID_COUNTER = [5000]


def _uuid7() -> str:
    _UUID_COUNTER[0] += 1
    n = _UUID_COUNTER[0]
    value = (0x019535D93DF7 << 80) | (0x7 << 76) | ((n & 0xFFF) << 64) | (0b10 << 62) | n
    return str(uuid.UUID(int=value))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _control_url() -> str:
    explicit = os.environ.get("LOOM_TEST_POSTGRES_URL")
    url = explicit or DEFAULT_CONTROL_URL
    try:
        with psycopg.connect(url, connect_timeout=2):
            return url
    except psycopg.Error:
        if explicit:
            raise
    subprocess.run(
        ["bash", "tools/postgres-test.sh", "up"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    with psycopg.connect(url, connect_timeout=10):
        return url


def _database_conninfo(control_url: str, database_name: str) -> str:
    params = conninfo_to_dict(control_url)
    params["dbname"] = database_name
    return make_conninfo(**params)


def _time(original: str = "建安十三年") -> dict:
    return {
        "original_text": original,
        "source_calendar": {
            "system": "chinese_lunisolar_regnal",
            "era": "建安",
            "era_year": 13,
            "season": None,
            "month": None,
            "day": None,
        },
        "normalized": None,
    }


def _event_payload(title: str) -> dict:
    return {
        "title": title,
        "type": "battle",
        "time": _time(),
        "participants": [],
        "places": [],
    }


def _segments(text: str, span: dict | None) -> list[dict]:
    if span is None:
        return [{"kind": "text", "text": text}]
    quote = span["quote"]
    start = text.index(quote)
    end = start + len(quote)
    segments: list[dict] = []
    if start > 0:
        segments.append({"kind": "text", "text": text[:start]})
    segments.append(
        {
            "kind": "event",
            "text": quote,
            "span": {
                "span_id": span["span_id"],
                "start": start,
                "end": end,
                "relation": span.get("relation", "current"),
            },
        }
    )
    if end < len(text):
        segments.append({"kind": "text", "text": text[end:]})
    return segments


class ReadingEventsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_t08_events_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        self.conn = psycopg.connect(self.database_url)
        apply_migrations(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name))
            )

    # -- fixtures ------------------------------------------------------

    def _seed_bundle_event(
        self, *, bundle: str, ref: str, title: str, source_title: str
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO chronicle.source_bundles(
                bundle_label, schema_version, source_ref, source_title,
                artifact_sha256, source_payload, bundle_payload
            ) VALUES (%s, '0.1', %s, %s, %s, '{}', '{}')
            ON CONFLICT (bundle_label) DO NOTHING
            """,
            (bundle, f"src_{bundle}", source_title, _sha256(f"bundle-{bundle}")),
        )
        self.conn.execute(
            """
            INSERT INTO chronicle.staged_events(
                bundle_label, record_ref, payload_sha256, payload
            ) VALUES (%s, %s, %s, %s)
            ON CONFLICT (bundle_label, record_ref) DO NOTHING
            """,
            (bundle, ref, _sha256(f"{bundle}:{ref}"), json.dumps(_event_payload(title))),
        )

    def _seed_catalog(self, events: list[dict]) -> str:
        """Persist a catalog whose ``events`` carry inline member metadata."""
        for event in events:
            for member in event["members"]:
                self._seed_bundle_event(
                    bundle=member["bundle"],
                    ref=member["ref"],
                    title=event["title"],
                    source_title=member["source_title"],
                )
        catalog = {
            "schema": "chronicle.canonical-catalog",
            "version": "0.1",
            "canonical_entities": [],
            "canonical_events": [
                {
                    "canonical_id": event["canonical_id"],
                    "representations": [
                        {"bundle": member["bundle"], "ref": member["ref"]}
                        for member in event["members"]
                    ],
                }
                for event in events
            ],
            "event_relations": [],
            "warnings": [],
        }
        catalog_sha, _ = canonical_store.persist_catalog(self.conn, catalog)
        return catalog_sha

    def _seed_publication(
        self, *, label: str, title: str, blocks: list[str], catalog_sha: str
    ) -> dict:
        document_id = control_plane.create_document(self.conn, title=title)
        revision_id, revision_no = control_plane.create_revision(
            self.conn,
            document_id=document_id,
            source_sha256=_sha256(f"{label}-source"),
            source_bytes=len("".join(blocks).encode("utf-8")),
            source_media_type="text/markdown",
        )
        worker = f"worker-{label}"
        job_id = control_plane.queue_job(self.conn, revision_id=revision_id)
        control_plane.claim_job(self.conn, worker=worker, job_id=job_id)
        section_id = control_plane.create_section(
            self.conn,
            job_id=job_id,
            section_index=0,
            label="章",
            source_start=0,
            source_end=len("".join(blocks)),
        )
        chunk_id = control_plane.record_chunk(
            self.conn,
            job_id=job_id,
            section_id=section_id,
            chunk_index=0,
            source_start=0,
            source_end=len("".join(blocks)),
            source_sha256=_sha256(f"{label}-source"),
            content_sha256=_sha256(f"{label}-chunk"),
        )
        control_plane.set_chunk_status(self.conn, chunk_id=chunk_id, status="running")
        run_id, _ = control_plane.record_chunk_run(
            self.conn, chunk_id=chunk_id, status="running", worker=worker
        )
        chapter_id = f"ch_{_sha256(f'{label}-chapter')[:24]}"
        artifact_sha256 = _sha256(f"{label}-artifact")
        blocks_payload = [
            {"block_id": f"t_{index:03d}", "text": text}
            for index, text in enumerate(blocks, start=1)
        ]
        self.conn.execute(
            """
            INSERT INTO chronicle.chapter_artifacts(
                artifact_sha256, job_id, revision_id, document_id, chapter_id,
                chapter_index, chunk_id, producing_run_id, request_fingerprint,
                candidate_sha256, payload
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                artifact_sha256,
                job_id,
                revision_id,
                document_id,
                chapter_id,
                0,
                chunk_id,
                run_id,
                _sha256(f"{label}-fingerprint"),
                _sha256(f"{label}-candidate"),
                json.dumps({"seed": True, "label": label}),
            ),
        )
        publication_id = _uuid7()
        assembled_sha = _sha256(f"{label}-assembled")
        publication = {
            "schema": "chronicle.chapter-publication",
            "version": "0.1",
            "chapter_id": chapter_id,
            "chapter_index": 0,
            "revision_id": str(revision_id),
            "artifact_sha256": artifact_sha256,
            "catalog_sha256": catalog_sha,
            "assembled_bundle_sha256": assembled_sha,
            "translation_blocks": blocks_payload,
        }
        self.conn.execute(
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
                catalog_sha,
                publication["assembled_bundle_sha256"],
                document_id,
                revision_id,
                job_id,
                chapter_id,
                json.dumps(publication),
            ),
        )
        # The chapter title lives in the publication's own assembled source
        # bundle, exactly where the production publish path records it.
        control_plane.record_output(
            self.conn,
            job_id=job_id,
            revision_id=revision_id,
            artifact_type="assembled-source-bundle",
            artifact_sha256=assembled_sha,
            payload={
                "bundle": {"seed": label},
                "report": {
                    "plan": {
                        "chapters": [
                            {"chapter_id": chapter_id, "title": f"{label}章标题"}
                        ]
                    }
                },
            },
        )
        return {
            "label": label,
            "document_id": document_id,
            "revision_id": revision_id,
            "chapter_id": chapter_id,
            "artifact_sha256": artifact_sha256,
            "publication_id": publication_id,
            "blocks": blocks_payload,
        }

    def _persist_stream(self, ctx: dict, *, catalog_sha: str, unit_specs: list[dict]) -> str:
        units: list[dict] = []
        occurrences: list[dict] = []
        for index, spec in enumerate(unit_specs):
            unit_id = "ru_" + _sha256(f"{ctx['label']}:{index}")[:24]
            text = spec["text"]
            units.append(
                {
                    "unit_id": unit_id,
                    "ordinal": index,
                    "publication_id": str(ctx["publication_id"]),
                    "artifact_sha256": ctx["artifact_sha256"],
                    "chapter_id": ctx["chapter_id"],
                    "block_id": ctx["blocks"][index]["block_id"],
                    "text_hash": _sha256(text),
                    "narrative_time": {
                        "mode": "events",
                        "status": "resolved",
                        "event_refs": list(spec.get("event_refs") or []),
                        "from_block_id": None,
                        "observations": [],
                        "year_key": "gregorian:208",
                        "period_key": "gregorian:208",
                        "year_label": "208年",
                        "period_label": "（月份未明确）",
                        "precision": "year",
                        "continues_previous": False,
                    },
                    "segments": _segments(text, spec.get("span")),
                    "context_entities": [],
                    "source_anchor_ids": [f"anc_{ctx['label']}_{index}"],
                    "group_id": f"tg_{ctx['label']}_{index}",
                    "continues_previous": False,
                }
            )
            for occurrence in spec.get("occurrences") or []:
                occurrences.append({"unit_id": unit_id, **occurrence})
        groups = [
            {
                "ordinal": index,
                "group_id": unit["group_id"],
                "first_unit_ordinal": index,
                "last_unit_ordinal": index,
                "first_unit_id": unit["unit_id"],
                "last_unit_id": unit["unit_id"],
                "unit_count": 1,
                "year_key": "gregorian:208",
                "period_key": "gregorian:208",
                "year_label": "208年",
                "period_label": "（月份未明确）",
                "precision": "year",
                "observations": [],
                "continues_previous": False,
            }
            for index, unit in enumerate(units)
        ]
        stream = {
            "revision_id": str(ctx["revision_id"]),
            "document_id": str(ctx["document_id"]),
            "origin_catalog_sha": catalog_sha,
            "manifest": {
                "schema": "chronicle.reading-stream",
                "version": "0.1",
                "revision_id": str(ctx["revision_id"]),
                "catalog_sha256": catalog_sha,
                "unit_ids": [unit["unit_id"] for unit in units],
            },
            "chapter_publication_ids": [str(ctx["publication_id"])],
            "units": units,
            "groups": groups,
            "event_occurrences": occurrences,
        }
        with self.conn.transaction():
            stream_id = reading_store.persist_reading_stream(self.conn, stream)
        return str(stream_id)

    def _span_occurrence(
        self, *, canonical_id: str, bundle: str, ref: str, span_id: str, relation: str
    ) -> dict:
        return {
            "event_kind": "span",
            "span_id": span_id,
            "canonical_event_id": canonical_id,
            "relation": relation,
            "bundle_label": bundle,
            "record_ref": ref,
        }

    # -- tests ---------------------------------------------------------

    def test_preview_does_not_cross_same_named_events(self) -> None:
        id_a = _uuid7()
        id_b = _uuid7()
        catalog = self._seed_catalog(
            [
                {
                    "canonical_id": id_a,
                    "title": "赤壁之战",
                    "members": [
                        {"bundle": "book-a", "ref": "evt_a", "source_title": "甲书"}
                    ],
                },
                {
                    "canonical_id": id_b,
                    "title": "赤壁之战",
                    "members": [
                        {"bundle": "book-b", "ref": "evt_b", "source_title": "乙书"}
                    ],
                },
            ]
        )
        ctx_a = self._seed_publication(
            label="a", title="甲书", blocks=["甲书写赤壁之战。"], catalog_sha=catalog
        )
        ctx_b = self._seed_publication(
            label="b", title="乙书", blocks=["乙书记赤壁。"], catalog_sha=catalog
        )
        self._persist_stream(
            ctx_a,
            catalog_sha=catalog,
            unit_specs=[
                {
                    "text": ctx_a["blocks"][0]["text"],
                    "span": {"span_id": "sp_a", "quote": "赤壁之战"},
                    "occurrences": [
                        self._span_occurrence(
                            canonical_id=id_a,
                            bundle="book-a",
                            ref="evt_a",
                            span_id="sp_a",
                            relation="current",
                        )
                    ],
                }
            ],
        )
        self._persist_stream(
            ctx_b,
            catalog_sha=catalog,
            unit_specs=[
                {
                    "text": ctx_b["blocks"][0]["text"],
                    "span": {"span_id": "sp_b", "quote": "赤壁"},
                    "occurrences": [
                        self._span_occurrence(
                            canonical_id=id_b,
                            bundle="book-b",
                            ref="evt_b",
                            span_id="sp_b",
                            relation="current",
                        )
                    ],
                }
            ],
        )

        preview = event_preview(
            self.conn, snapshot_catalog_sha=catalog, canonical_event_id=id_a
        )
        self.assertEqual(preview["name"], "赤壁之战")
        self.assertEqual(preview["source_count"], 1)
        self.assertEqual([source["source_title"] for source in preview["sources"]], ["甲书"])
        self.assertIn("甲书", preview["sources"][0]["excerpt"])

        page = event_targets(self.conn, snapshot_catalog_sha=catalog, canonical_event_id=id_a)
        self.assertEqual([target["span_id"] for target in page["targets"]], ["sp_a"])
        self.assertEqual([target["source_title"] for target in page["targets"]], ["甲书"])

    def test_targets_paginate_multiple_sources_with_totals(self) -> None:
        event_id = _uuid7()
        labels = ["a", "b", "c"]
        members = [
            {"bundle": f"book-{label}", "ref": f"evt_{label}", "source_title": f"{label}书"}
            for label in labels
        ]
        catalog = self._seed_catalog(
            [{"canonical_id": event_id, "title": "赤壁之战", "members": members}]
        )
        # Source a and b are occurrences, source c is only a mention.
        for index, (label, member) in enumerate(zip(labels, members)):
            ctx = self._seed_publication(
                label=label,
                title=member["source_title"],
                blocks=[f"{label}书叙赤壁之战经过很长。"],
                catalog_sha=catalog,
            )
            relation = "current" if index < 2 else "retrospective"
            self._persist_stream(
                ctx,
                catalog_sha=catalog,
                unit_specs=[
                    {
                        "text": ctx["blocks"][0]["text"],
                        "span": {"span_id": f"sp_{label}", "quote": "赤壁之战"},
                        "occurrences": [
                            self._span_occurrence(
                                canonical_id=event_id,
                                bundle=member["bundle"],
                                ref=member["ref"],
                                span_id=f"sp_{label}",
                                relation=relation,
                            )
                        ],
                    }
                ],
            )

        first = event_targets(
            self.conn, snapshot_catalog_sha=catalog, canonical_event_id=event_id, limit=1
        )
        self.assertEqual(len(first["targets"]), 1)
        self.assertTrue(first["has_more"])
        self.assertIsNotNone(first["next_cursor"])
        self.assertEqual(first["current_count"], 2)
        self.assertEqual(first["mention_count"], 1)
        self.assertEqual(first["targets"][0]["relation"], "current")

        collected = list(first["targets"])
        cursor = first["next_cursor"]
        while cursor:
            page = event_targets(
                self.conn,
                snapshot_catalog_sha=catalog,
                canonical_event_id=event_id,
                limit=1,
                cursor=cursor,
            )
            collected.extend(page["targets"])
            cursor = page["next_cursor"] if page["has_more"] else None
        self.assertEqual(len(collected), 3)
        # Every source is reachable across pages; current sorts before mention.
        self.assertEqual(collected[0]["relation"], "current")
        self.assertEqual(collected[1]["relation"], "current")
        self.assertEqual(collected[2]["relation"], "mention")
        self.assertEqual(len({target["stream_id"] for target in collected}), 3)

    def test_preview_only_mention_has_no_excerpt(self) -> None:
        event_id = _uuid7()
        catalog = self._seed_catalog(
            [
                {
                    "canonical_id": event_id,
                    "title": "赤壁之战",
                    "members": [
                        {"bundle": "book-a", "ref": "evt_a", "source_title": "甲书"}
                    ],
                }
            ]
        )
        ctx = self._seed_publication(
            label="a", title="甲书", blocks=["后来回忆赤壁之战。"], catalog_sha=catalog
        )
        self._persist_stream(
            ctx,
            catalog_sha=catalog,
            unit_specs=[
                {
                    "text": ctx["blocks"][0]["text"],
                    "span": {"span_id": "sp_a", "quote": "赤壁之战"},
                    "occurrences": [
                        self._span_occurrence(
                            canonical_id=event_id,
                            bundle="book-a",
                            ref="evt_a",
                            span_id="sp_a",
                            relation="retrospective",
                        )
                    ],
                }
            ],
        )

        preview = event_preview(
            self.conn, snapshot_catalog_sha=catalog, canonical_event_id=event_id
        )
        self.assertIsNone(preview["sources"][0]["excerpt"])
        self.assertFalse(preview["sources"][0]["excerpt_more"])
        self.assertEqual(len(preview["sources"][0]["observations"]), 1)

        page = event_targets(
            self.conn, snapshot_catalog_sha=catalog, canonical_event_id=event_id
        )
        self.assertEqual(page["current_count"], 0)
        self.assertEqual(page["mention_count"], 1)
        self.assertEqual(page["targets"][0]["relation"], "mention")

    def test_event_with_no_occurrence_stays_usable(self) -> None:
        event_id = _uuid7()
        catalog = self._seed_catalog(
            [
                {
                    "canonical_id": event_id,
                    "title": "未见正文之战",
                    "members": [
                        {"bundle": "book-a", "ref": "evt_a", "source_title": "甲书"}
                    ],
                }
            ]
        )
        preview = event_preview(
            self.conn, snapshot_catalog_sha=catalog, canonical_event_id=event_id
        )
        self.assertEqual(preview["source_count"], 1)
        self.assertIsNone(preview["sources"][0]["excerpt"])
        page = event_targets(
            self.conn, snapshot_catalog_sha=catalog, canonical_event_id=event_id
        )
        self.assertEqual(page["targets"], [])
        self.assertEqual(page["current_count"], 0)
        self.assertEqual(page["mention_count"], 0)
        self.assertFalse(page["has_more"])
        self.assertIsNone(page["next_cursor"])

    def test_older_snapshot_does_not_leak_later_member(self) -> None:
        event_id = _uuid7()
        catalog_a = self._seed_catalog(
            [
                {
                    "canonical_id": event_id,
                    "title": "赤壁之战",
                    "members": [
                        {"bundle": "book-a", "ref": "evt_a", "source_title": "甲书"}
                    ],
                }
            ]
        )
        ctx_a = self._seed_publication(
            label="a", title="甲书", blocks=["甲书叙赤壁之战。"], catalog_sha=catalog_a
        )
        self._persist_stream(
            ctx_a,
            catalog_sha=catalog_a,
            unit_specs=[
                {
                    "text": ctx_a["blocks"][0]["text"],
                    "span": {"span_id": "sp_a", "quote": "赤壁之战"},
                    "occurrences": [
                        self._span_occurrence(
                            canonical_id=event_id,
                            bundle="book-a",
                            ref="evt_a",
                            span_id="sp_a",
                            relation="current",
                        )
                    ],
                }
            ],
        )

        # A later catalog adds a second representation for the same event, and
        # a stream published under it.
        catalog_b = self._seed_catalog(
            [
                {
                    "canonical_id": event_id,
                    "title": "赤壁之战",
                    "members": [
                        {"bundle": "book-a", "ref": "evt_a", "source_title": "甲书"},
                        {"bundle": "book-b", "ref": "evt_b", "source_title": "乙书"},
                    ],
                }
            ]
        )
        ctx_b = self._seed_publication(
            label="b", title="乙书", blocks=["乙书亦叙赤壁之战。"], catalog_sha=catalog_b
        )
        self._persist_stream(
            ctx_b,
            catalog_sha=catalog_b,
            unit_specs=[
                {
                    "text": ctx_b["blocks"][0]["text"],
                    "span": {"span_id": "sp_b", "quote": "赤壁之战"},
                    "occurrences": [
                        self._span_occurrence(
                            canonical_id=event_id,
                            bundle="book-b",
                            ref="evt_b",
                            span_id="sp_b",
                            relation="current",
                        )
                    ],
                }
            ],
        )

        old_preview = event_preview(
            self.conn, snapshot_catalog_sha=catalog_a, canonical_event_id=event_id
        )
        self.assertEqual(old_preview["source_count"], 1)
        self.assertEqual(
            [source["source_title"] for source in old_preview["sources"]], ["甲书"]
        )
        old_targets = event_targets(
            self.conn, snapshot_catalog_sha=catalog_a, canonical_event_id=event_id
        )
        self.assertEqual([target["span_id"] for target in old_targets["targets"]], ["sp_a"])
        self.assertEqual(old_targets["current_count"], 1)

        new_preview = event_preview(
            self.conn, snapshot_catalog_sha=catalog_b, canonical_event_id=event_id
        )
        self.assertEqual(new_preview["source_count"], 2)
        new_targets = event_targets(
            self.conn, snapshot_catalog_sha=catalog_b, canonical_event_id=event_id
        )
        self.assertEqual(
            {target["span_id"] for target in new_targets["targets"]}, {"sp_a", "sp_b"}
        )

    def test_cursor_is_bound_to_snapshot(self) -> None:
        event_id = _uuid7()
        catalog = self._seed_catalog(
            [
                {
                    "canonical_id": event_id,
                    "title": "赤壁之战",
                    "members": [
                        {"bundle": "book-a", "ref": "evt_a", "source_title": "甲书"}
                    ],
                }
            ]
        )
        for label in ("a", "b"):
            ctx = self._seed_publication(
                label=label,
                title=f"{label}书",
                blocks=[f"{label}书叙赤壁之战。"],
                catalog_sha=catalog,
            )
            self._persist_stream(
                ctx,
                catalog_sha=catalog,
                unit_specs=[
                    {
                        "text": ctx["blocks"][0]["text"],
                        "span": {"span_id": f"sp_{label}", "quote": "赤壁之战"},
                        "occurrences": [
                            self._span_occurrence(
                                canonical_id=event_id,
                                bundle="book-a",
                                ref="evt_a",
                                span_id=f"sp_{label}",
                                relation="current",
                            )
                        ],
                    }
                ],
            )
        # Build a second, distinct snapshot that still lists the event so the
        # cursor's snapshot binding is genuinely exercised.
        other_catalog = self._seed_catalog(
            [
                {
                    "canonical_id": event_id,
                    "title": "赤壁之战",
                    "members": [
                        {"bundle": "book-a", "ref": "evt_a", "source_title": "甲书"}
                    ],
                },
                {
                    "canonical_id": _uuid7(),
                    "title": "另一个事件",
                    "members": [
                        {"bundle": "book-c", "ref": "evt_c", "source_title": "丙书"}
                    ],
                },
            ]
        )
        first = event_targets(
            self.conn, snapshot_catalog_sha=catalog, canonical_event_id=event_id, limit=1
        )
        self.assertTrue(first["has_more"])
        with self.assertRaises(ReadModelError):
            event_targets(
                self.conn,
                snapshot_catalog_sha=other_catalog,
                canonical_event_id=event_id,
                limit=1,
                cursor=first["next_cursor"],
            )

    def test_unknown_snapshot_and_non_member_event(self) -> None:
        event_id = _uuid7()
        catalog = self._seed_catalog(
            [
                {
                    "canonical_id": event_id,
                    "title": "赤壁之战",
                    "members": [
                        {"bundle": "book-a", "ref": "evt_a", "source_title": "甲书"}
                    ],
                }
            ]
        )
        other_id = _uuid7()
        with self.assertRaises(ReadModelNotFound):
            event_preview(
                self.conn, snapshot_catalog_sha=catalog, canonical_event_id=other_id
            )
        with self.assertRaises(ReadModelNotFound):
            event_targets(
                self.conn, snapshot_catalog_sha=catalog, canonical_event_id=other_id
            )
        with self.assertRaises(ReadModelNotFound):
            event_preview(
                self.conn, snapshot_catalog_sha="0" * 64, canonical_event_id=event_id
            )
        with self.assertRaises(ReadModelError):
            event_targets(
                self.conn, snapshot_catalog_sha="bad", canonical_event_id=event_id
            )

    def test_forged_non_uuid_cursor_is_bad_request(self) -> None:
        event_id = _uuid7()
        catalog = self._seed_catalog(
            [
                {
                    "canonical_id": event_id,
                    "title": "赤壁之战",
                    "members": [
                        {"bundle": "book-a", "ref": "evt_a", "source_title": "甲书"}
                    ],
                }
            ]
        )
        forged = {
            "v": 1,
            "catalog": catalog,
            "event": event_id,
            "rank": 0,
            "stream": "not-a-uuid",
            "ordinal": 0,
            "span": "sp_a",
        }
        cursor = (
            base64.urlsafe_b64encode(
                json.dumps(forged, separators=(",", ":"), sort_keys=True).encode("utf-8")
            )
            .decode("ascii")
            .rstrip("=")
        )
        # A forged stream key must be a 400 (ReadModelError), never reach the
        # database as %s::uuid and surface as a 503.
        with self.assertRaises(ReadModelError):
            event_targets(
                self.conn,
                snapshot_catalog_sha=catalog,
                canonical_event_id=event_id,
                cursor=cursor,
            )

    def test_missing_span_segment_fails_explicitly(self) -> None:
        event_id = _uuid7()
        catalog = self._seed_catalog(
            [
                {
                    "canonical_id": event_id,
                    "title": "赤壁之战",
                    "members": [
                        {"bundle": "book-a", "ref": "evt_a", "source_title": "甲书"}
                    ],
                }
            ]
        )
        ctx = self._seed_publication(
            label="a", title="甲书", blocks=["甲书叙赤壁之战。"], catalog_sha=catalog
        )
        # The occurrence claims a span the unit's segments do not contain:
        # the reading index and the body disagree and must fail explicitly.
        self._persist_stream(
            ctx,
            catalog_sha=catalog,
            unit_specs=[
                {
                    "text": ctx["blocks"][0]["text"],
                    "occurrences": [
                        self._span_occurrence(
                            canonical_id=event_id,
                            bundle="book-a",
                            ref="evt_a",
                            span_id="sp_missing",
                            relation="current",
                        )
                    ],
                }
            ],
        )
        with self.assertRaises(ReadModelInconsistency):
            event_targets(
                self.conn, snapshot_catalog_sha=catalog, canonical_event_id=event_id
            )

    def test_targets_return_source_chapter_title(self) -> None:
        event_id = _uuid7()
        catalog = self._seed_catalog(
            [
                {
                    "canonical_id": event_id,
                    "title": "赤壁之战",
                    "members": [
                        {"bundle": "book-a", "ref": "evt_a", "source_title": "甲书"}
                    ],
                }
            ]
        )
        ctx = self._seed_publication(
            label="a", title="甲书", blocks=["甲书叙赤壁之战。"], catalog_sha=catalog
        )
        self._persist_stream(
            ctx,
            catalog_sha=catalog,
            unit_specs=[
                {
                    "text": ctx["blocks"][0]["text"],
                    "span": {"span_id": "sp_a", "quote": "赤壁之战"},
                    "occurrences": [
                        self._span_occurrence(
                            canonical_id=event_id,
                            bundle="book-a",
                            ref="evt_a",
                            span_id="sp_a",
                            relation="current",
                        )
                    ],
                }
            ],
        )
        page = event_targets(
            self.conn, snapshot_catalog_sha=catalog, canonical_event_id=event_id
        )
        self.assertEqual(page["targets"][0]["chapter_title"], "a章标题")
        self.assertEqual(page["targets"][0]["source_title"], "甲书")


if __name__ == "__main__":
    unittest.main()
