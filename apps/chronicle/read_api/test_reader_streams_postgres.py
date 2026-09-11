"""PostgreSQL 18 integration tests for the Chronicle C2-R2-T07 stream API.

Covers ``continuous-reading.md`` sections 5-6 on top of the T05 store:

- the directory resolves/echoes a fixed snapshot (newest catalog by
  ``publication_sequence``) and never mixes revisions;
- bidirectional body paging reaches every unit exactly once in source
  order and stops before the 2 MiB page budget without truncating a unit;
- the 4,900th synthetic unit is located directly through its indexed
  ``unit_id`` without reading the preceding bodies;
- a group spanning a page boundary keeps the same ``group_id`` /
  ``continues_previous`` and its first/last locators point at real units;
- cursors from another scope, snapshot, stream or direction are rejected;
- an old stream keeps reading its old text, unknown / unpublished /
  cross-stream units stay invisible and every GET is read-only.

Fixtures seed the real control-plane/chapter rows and persist a compiled
stream through the production T05 write entry; that is a test loading path,
not a second production success path.
"""

from __future__ import annotations

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
PERSISTENCE = ROOT / "apps" / "chronicle" / "persistence"
for path in (str(HERE), str(PERSISTENCE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import canonical_store  # noqa: E402
import control_plane  # noqa: E402
import reader_streams  # noqa: E402
import reading_contract  # noqa: E402
import reading_store  # noqa: E402
from common import canonical_json_bytes  # noqa: E402
from migrations import apply_migrations  # noqa: E402

DEFAULT_CONTROL_URL = "postgresql://loom:loom@127.0.0.1:15432/loom_control"

_UUID_COUNTER = [5000]


def _uuid7() -> str:
    _UUID_COUNTER[0] += 1
    n = _UUID_COUNTER[0]
    value = (0x019535D93DF7 << 80) | (0x7 << 76) | ((n & 0xFFF) << 64) | (0b10 << 62) | n
    return str(uuid.UUID(int=value))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _unit_key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


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


def _narrative_time(*, year: int, continues: bool) -> dict:
    key = f"gregorian:{year}"
    return {
        "mode": "events",
        "status": "resolved",
        "event_refs": [],
        "from_block_id": None,
        "observations": [],
        "year_key": key,
        "period_key": key,
        "year_label": f"{year}年",
        "period_label": "（月份未明确）",
        "precision": "year",
        "continues_previous": continues,
    }


class ReaderStreamsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_t07_test_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)

    def tearDown(self) -> None:
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name))
            )

    def _connect_ready(self):
        conn = psycopg.connect(self.database_url)
        apply_migrations(conn)
        return conn

    # -- fixtures ------------------------------------------------------

    def _seed_catalog(self, conn, *, label: str, event_refs: list[tuple[str, str]] | None = None) -> str:
        catalog = {
            "schema": "chronicle.canonical-catalog",
            "version": "0.1",
            "canonical_entities": [],
            "canonical_events": [
                {
                    "canonical_id": _uuid7(),
                    "representations": [{"bundle": bundle, "ref": ref}],
                }
                for bundle, ref in (event_refs or [])
            ],
            "event_relations": [],
            # Unique per fixture so two otherwise-empty catalogs cannot
            # collapse to the same content hash.
            "warnings": [{"code": f"fixture:{label}"}],
        }
        catalog_sha, _ = canonical_store.persist_catalog(conn, catalog)
        return catalog_sha

    def _seed_chapter(
        self,
        conn,
        *,
        document_id,
        label: str,
        title: str,
        blocks: list[str],
        catalog_sha: str,
        chapter_index: int = 0,
        revision_id=None,
    ) -> dict:
        if revision_id is None:
            revision_id, revision_no = control_plane.create_revision(
                conn,
                document_id=document_id,
                source_sha256=_sha256(f"{label}-source"),
                source_bytes=len("".join(blocks).encode("utf-8")),
                source_media_type="text/markdown",
            )
        else:
            revision_no = conn.execute(
                "SELECT revision_no FROM chronicle.document_revisions"
                " WHERE revision_id = %s",
                (revision_id,),
            ).fetchone()[0]
            document_id = conn.execute(
                "SELECT document_id FROM chronicle.document_revisions"
                " WHERE revision_id = %s",
                (revision_id,),
            ).fetchone()[0]
        worker = f"worker-{label}"
        job_id = control_plane.queue_job(conn, revision_id=revision_id)
        control_plane.claim_job(conn, worker=worker, job_id=job_id)
        section_id = control_plane.create_section(
            conn,
            job_id=job_id,
            section_index=0,
            label="章",
            source_start=0,
            source_end=len("".join(blocks)),
        )
        chunk_id = control_plane.record_chunk(
            conn,
            job_id=job_id,
            section_id=section_id,
            chunk_index=0,
            source_start=0,
            source_end=len("".join(blocks)),
            source_sha256=_sha256(f"{label}-source"),
            content_sha256=_sha256(f"{label}-chunk"),
        )
        control_plane.set_chunk_status(conn, chunk_id=chunk_id, status="running")
        run_id, _ = control_plane.record_chunk_run(
            conn, chunk_id=chunk_id, status="running", worker=worker
        )
        chapter_id = "ch_" + _unit_key(label, "chapter")[:24]
        artifact_sha256 = _sha256(f"{label}-artifact")
        blocks_payload = [
            {"block_id": f"t_{index:04d}", "text": text}
            for index, text in enumerate(blocks, start=1)
        ]
        conn.execute(
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
                chapter_index,
                chunk_id,
                run_id,
                _sha256(f"{label}-fingerprint"),
                _sha256(f"{label}-candidate"),
                json.dumps({"seed": True, "label": label}),
            ),
        )
        publication_id = _uuid7()
        publication = {
            "schema": "chronicle.chapter-publication",
            "version": "0.1",
            "chapter_id": chapter_id,
            "chapter_index": chapter_index,
            "revision_id": str(revision_id),
            "artifact_sha256": artifact_sha256,
            "catalog_sha256": catalog_sha,
            "assembled_bundle_sha256": _sha256(f"{label}-assembled"),
            "translation_blocks": blocks_payload,
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
        return {
            "label": label,
            "title": title,
            "document_id": document_id,
            "revision_id": revision_id,
            "revision_no": revision_no,
            "job_id": job_id,
            "chunk_id": chunk_id,
            "run_id": run_id,
            "chapter_id": chapter_id,
            "artifact_sha256": artifact_sha256,
            "publication_id": publication_id,
            "blocks": blocks_payload,
        }

    def _build_stream(
        self,
        ctx: dict,
        *,
        catalog_sha: str,
        group_size: int = 1,
        unit_overrides: dict[int, dict] | None = None,
        tag: str = "v1",
        extra_ctxs: list[dict] | None = None,
        group_plan: list[dict] | None = None,
    ) -> dict:
        overrides = unit_overrides or {}
        contexts = [ctx] + list(extra_ctxs or [])
        units: list[dict] = []
        for context in contexts:
            for block in context["blocks"]:
                index = len(units)
                override = overrides.get(index, {})
                text = override.get("text", block["text"])
                unit_id = "ru_" + _unit_key(
                    context["label"], str(context["revision_id"]), block["block_id"]
                )[:24]
                units.append(
                    {
                        "unit_id": override.get("unit_id", unit_id),
                        "ordinal": index,
                        "publication_id": str(context["publication_id"]),
                        "artifact_sha256": context["artifact_sha256"],
                        "chapter_id": context["chapter_id"],
                        "block_id": block["block_id"],
                        "text_hash": _sha256(text),
                        "narrative_time": {},
                        "segments": override.get(
                            "segments", [{"kind": "text", "text": text}]
                        ),
                        "context_entities": override.get("context_entities", []),
                        "source_anchor_ids": override.get(
                            "source_anchor_ids", [f"anc_{block['block_id']}"]
                        ),
                        "group_id": "",
                        "continues_previous": False,
                    }
                )
        count = len(units)

        groups: list[dict] = []
        if group_plan is not None:
            for spec in group_plan:
                first = int(spec["first"])
                last = int(spec["last"])
                group_id = "tg_" + _unit_key(ctx["label"], str(spec.get("key", first)))[:16]
                narrative = {
                    "mode": spec.get("mode", "events"),
                    "status": spec.get("status", "resolved"),
                    "event_refs": [],
                    "from_block_id": None,
                    "observations": [],
                    "year_key": spec.get("year_key", "unknown"),
                    "period_key": spec.get("period_key", "unknown"),
                    "year_label": spec.get("year_label"),
                    "period_label": spec.get("period_label", "时间未明确"),
                    "precision": spec.get("precision", "unknown"),
                }
                for ordinal in range(first, last + 1):
                    unit = units[ordinal]
                    unit["group_id"] = group_id
                    unit["continues_previous"] = ordinal != first
                    unit["narrative_time"] = {
                        **narrative,
                        "continues_previous": ordinal != first,
                    }
                groups.append(
                    {
                        "ordinal": len(groups),
                        "group_id": group_id,
                        "first_unit_ordinal": first,
                        "last_unit_ordinal": last,
                        "first_unit_id": units[first]["unit_id"],
                        "last_unit_id": units[last]["unit_id"],
                        "unit_count": last - first + 1,
                        "year_key": narrative["year_key"],
                        "period_key": narrative["period_key"],
                        "year_label": narrative["year_label"],
                        "period_label": narrative["period_label"],
                        "precision": narrative["precision"],
                        "observations": [],
                        "continues_previous": False,
                    }
                )
        else:
            for index, unit in enumerate(units):
                group_index = index // group_size
                continues = index % group_size != 0
                group_id = "tg_" + _unit_key(ctx["label"], str(group_index))[:16]
                unit["group_id"] = group_id
                unit["continues_previous"] = continues
                unit["narrative_time"] = _narrative_time(
                    year=208 + group_index, continues=continues
                )
                if continues:
                    groups[-1]["last_unit_ordinal"] = index
                    groups[-1]["last_unit_id"] = unit["unit_id"]
                    groups[-1]["unit_count"] += 1
                else:
                    groups.append(
                        {
                            "ordinal": group_index,
                            "group_id": group_id,
                            "first_unit_ordinal": index,
                            "last_unit_ordinal": index,
                            "first_unit_id": unit["unit_id"],
                            "last_unit_id": unit["unit_id"],
                            "unit_count": 1,
                            "year_key": f"gregorian:{208 + group_index}",
                            "period_key": f"gregorian:{208 + group_index}",
                            "year_label": f"{208 + group_index}年",
                            "period_label": "（月份未明确）",
                            "precision": "year",
                            "observations": [],
                            "continues_previous": False,
                        }
                    )

        publications: list[str] = []
        chapters: list[dict] = []
        for context in contexts:
            if str(context["publication_id"]) not in publications:
                publications.append(str(context["publication_id"]))
            chapters.append(
                {
                    "chapter_id": context["chapter_id"],
                    "chapter_index": context.get("chapter_index", 0),
                    "publication_id": str(context["publication_id"]),
                    "artifact_sha256": context["artifact_sha256"],
                    "unit_count": sum(
                        1
                        for unit in units
                        if unit["publication_id"] == str(context["publication_id"])
                    ),
                    "title": None,
                }
            )

        full_text = "".join(
            "".join(segment["text"] for segment in unit["segments"])
            for unit in units
        )
        manifest = {
            "schema": "chronicle.reading-stream-manifest",
            "version": "0.1",
            "tag": tag,
            "revision_id": str(ctx["revision_id"]),
            "catalog_sha": catalog_sha,
            "source_title": ctx["title"],
            "full_text_sha256": _sha256(full_text),
            "unit_count": count,
            "group_count": len(groups),
            "chapters": chapters,
        }
        return {
            "revision_id": str(ctx["revision_id"]),
            "document_id": str(ctx["document_id"]),
            "origin_catalog_sha": catalog_sha,
            "manifest": manifest,
            "chapter_publication_ids": publications,
            "units": units,
            "groups": groups,
            "event_occurrences": [],
        }

    def _publish(self, conn, stream: dict):
        with conn.transaction():
            return reading_store.persist_reading_stream(conn, stream)

    def _single_source_stream(self, conn, *, label="a", blocks=("正文一。",), group_size=1):
        document_id = control_plane.create_document(conn, title=f"{label}书")
        catalog = self._seed_catalog(conn, label=label)
        ctx = self._seed_chapter(
            conn,
            document_id=document_id,
            label=label,
            title=f"{label}书",
            blocks=list(blocks),
            catalog_sha=catalog,
        )
        stream = self._build_stream(ctx, catalog_sha=catalog, group_size=group_size)
        stream_id = self._publish(conn, stream)
        return {"ctx": ctx, "catalog": catalog, "stream_id": stream_id, "stream": stream}

    # -- directory + snapshot ------------------------------------------

    def test_directory_resolves_and_echoes_snapshot(self) -> None:
        with self._connect_ready() as conn:
            document_id = control_plane.create_document(conn, title="甲书")
            catalog_1 = self._seed_catalog(conn, label="a")
            ctx_a = self._seed_chapter(
                conn,
                document_id=document_id,
                label="a",
                title="甲书",
                blocks=["甲书正文。"],
                catalog_sha=catalog_1,
            )
            stream_a = self._publish(conn, self._build_stream(ctx_a, catalog_sha=catalog_1))

            catalog_2 = self._seed_catalog(conn, label="b")
            ctx_b = self._seed_chapter(
                conn,
                document_id=control_plane.create_document(conn, title="乙书"),
                label="b",
                title="乙书",
                blocks=["乙书正文。"],
                catalog_sha=catalog_2,
            )
            stream_b = self._publish(conn, self._build_stream(ctx_b, catalog_sha=catalog_2))

            # No catalog: pin the newest catalog once and echo it.
            default_listing = reader_streams.list_streams(conn, limit=20)
            self.assertEqual(default_listing["snapshot"]["catalog_sha"], catalog_2)
            self.assertEqual(default_listing["schema"], "chronicle.reading-stream-directory")
            listed = {item["stream_id"] for item in default_listing["page"]["streams"]}
            self.assertEqual(listed, {str(stream_a), str(stream_b)})

            # The old snapshot sees only the stream published under it.
            old_listing = reader_streams.list_streams(conn, catalog_sha=catalog_1)
            self.assertEqual(
                [item["stream_id"] for item in old_listing["page"]["streams"]],
                [str(stream_a)],
            )
            self.assertTrue(old_listing["query"]["cursor"] is None)

    def test_directory_cursor_is_snapshot_bound(self) -> None:
        with self._connect_ready() as conn:
            document_id = control_plane.create_document(conn, title="甲书")
            catalog_1 = self._seed_catalog(conn, label="a")
            catalog_2 = self._seed_catalog(conn, label="b")
            for label, catalog in (("a", catalog_1), ("b", catalog_2)):
                ctx = self._seed_chapter(
                    conn,
                    document_id=document_id,
                    label=label,
                    title="甲书",
                    blocks=[f"{label}正文。"],
                    catalog_sha=catalog,
                )
                self._publish(conn, self._build_stream(ctx, catalog_sha=catalog))

            first = reader_streams.list_streams(conn, catalog_sha=catalog_2, limit=1)
            self.assertTrue(first["page"]["has_more"])
            cursor = first["page"]["next_cursor"]
            second = reader_streams.list_streams(
                conn, catalog_sha=catalog_2, limit=1, cursor=cursor
            )
            self.assertEqual(len(second["page"]["streams"]), 1)
            with self.assertRaises(reader_streams.ReadingStreamBadRequest):
                reader_streams.list_streams(conn, catalog_sha=catalog_1, limit=1, cursor=cursor)

    # -- bidirectional traversal ---------------------------------------

    def test_bidirectional_traversal_visits_every_unit_once(self) -> None:
        with self._connect_ready() as conn:
            fixture = self._single_source_stream(
                conn, label="a", blocks=[f"正文{index}。" for index in range(5)]
            )
            stream_id = fixture["stream_id"]

            forward: list[int] = []
            cursor = None
            pages = 0
            while True:
                envelope = reader_streams.stream_units(
                    conn, stream_id=stream_id, limit=2, cursor=cursor
                )
                page = envelope["page"]
                errors = reading_contract.reading_response_errors("stream_page", page)
                self.assertEqual(errors, [])
                ordinals = [unit["ordinal"] for unit in page["units"]]
                self.assertEqual(ordinals, sorted(ordinals))
                forward.extend(ordinals)
                pages += 1
                self.assertLess(pages, 10)
                if not page["has_next"]:
                    break
                cursor = page["next_cursor"]
            self.assertEqual(forward, [0, 1, 2, 3, 4])

            backward: list[int] = []
            envelope = reader_streams.stream_units(
                conn, stream_id=stream_id, limit=2, direction="backward"
            )
            page = envelope["page"]
            self.assertEqual([unit["ordinal"] for unit in page["units"]], [3, 4])
            self.assertTrue(page["has_previous"])
            backward[:0] = [unit["ordinal"] for unit in page["units"]]
            cursor = page["prev_cursor"]
            while cursor is not None:
                envelope = reader_streams.stream_units(
                    conn, stream_id=stream_id, limit=2, cursor=cursor, direction="backward"
                )
                page = envelope["page"]
                backward[:0] = [unit["ordinal"] for unit in page["units"]]
                cursor = page["prev_cursor"]
            self.assertEqual(backward, [0, 1, 2, 3, 4])

            # Every unit is reachable and each text reassembles verbatim.
            merged: dict[int, str] = {}
            cursor = None
            while True:
                envelope = reader_streams.stream_units(
                    conn, stream_id=stream_id, limit=2, cursor=cursor
                )
                page = envelope["page"]
                for unit in page["units"]:
                    self.assertEqual(
                        "".join(segment["text"] for segment in unit["segments"]),
                        fixture["stream"]["units"][unit["ordinal"]]["segments"][0]["text"],
                    )
                    merged[unit["ordinal"]] = unit["unit_id"]
                if not page["has_next"]:
                    break
                cursor = page["next_cursor"]
            self.assertEqual(sorted(merged), [0, 1, 2, 3, 4])

    # -- page byte budget ----------------------------------------------

    def test_page_budget_stops_without_truncating_a_unit(self) -> None:
        with self._connect_ready() as conn:
            block_text = "a" * 200_000
            blocks = [f"{block_text}{index}" for index in range(11)]
            fixture = self._single_source_stream(conn, label="big", blocks=blocks)
            envelope = reader_streams.stream_units(
                conn, stream_id=fixture["stream_id"], limit=20
            )
            page = envelope["page"]
            self.assertLess(len(page["units"]), 11)
            self.assertTrue(page["has_next"])
            self.assertIsNotNone(page["next_cursor"])
            self.assertLessEqual(len(canonical_json_bytes(page)), 2 * 1024 * 1024)
            self.assertEqual(reading_contract.reading_response_errors("stream_page", page), [])
            for unit in page["units"]:
                self.assertEqual(
                    "".join(segment["text"] for segment in unit["segments"]), 
                    blocks[unit["ordinal"]],
                )

            # The dropped tail is reachable through the next cursor.
            following = reader_streams.stream_units(
                conn, stream_id=fixture["stream_id"], limit=20, cursor=page["next_cursor"]
            )
            self.assertTrue(following["page"]["units"])
            self.assertEqual(
                following["page"]["units"][0]["ordinal"], page["units"][-1]["ordinal"] + 1
            )

    # -- locate ---------------------------------------------------------

    def test_locate_4900th_unit_is_direct(self) -> None:
        with self._connect_ready() as conn:
            blocks = [f"合成段落{index}。" for index in range(4901)]
            fixture = self._single_source_stream(
                conn, label="synthetic", blocks=blocks, group_size=100
            )
            stream_id = fixture["stream_id"]
            target = fixture["stream"]["units"][4900]
            self.assertEqual(target["ordinal"], 4900)

            captured: list[dict] = []
            original = reading_store.read_reading_units

            def _spy(*args, **kwargs):
                captured.append(kwargs)
                return original(*args, **kwargs)

            reading_store.read_reading_units = _spy
            try:
                envelope = reader_streams.locate_unit(
                    conn, stream_id=stream_id, unit_id=target["unit_id"], limit=5
                )
            finally:
                reading_store.read_reading_units = original

            page = envelope["page"]
            self.assertEqual(page["locator"], {
                "stream_id": str(stream_id),
                "catalog_sha": fixture["catalog"],
                "unit_id": target["unit_id"],
            })
            self.assertEqual(page["target_ordinal"], 4900)
            self.assertEqual(page["units"][0]["ordinal"], 4900)
            self.assertEqual(page["units"][0]["unit_id"], target["unit_id"])
            self.assertTrue(all(unit["ordinal"] >= 4900 for unit in page["units"]))
            self.assertEqual(page["group_ordinal"], 49)
            self.assertTrue(any(kwargs.get("after_ordinal") == 4899 for kwargs in captured))

            # The adjacent group page entry opens at the target's group.
            group_page = reader_streams.stream_groups(
                conn, stream_id=stream_id, cursor=page["group_cursor"], limit=1
            )
            self.assertEqual(group_page["page"]["groups"][0]["group_id"], target["group_id"])
            self.assertEqual(group_page["page"]["groups"][0]["ordinal"], 49)

    def test_locate_page_respects_page_budget(self) -> None:
        """Regression: the final locate payload, metadata included, is <=2 MiB.

        The target's full unit is no longer duplicated outside the budgeted
        unit list, and the 2 MiB cap is measured on the serialized locate
        page, never truncating the target unit.
        """
        with self._connect_ready() as conn:
            block_text = "a" * 200_000
            blocks = [f"{block_text}{index}" for index in range(11)]
            fixture = self._single_source_stream(conn, label="locate-big", blocks=blocks)
            stream_id = fixture["stream_id"]

            for target_ordinal in (0, 7, 10):
                target = fixture["stream"]["units"][target_ordinal]
                page = reader_streams.locate_unit(
                    conn, stream_id=stream_id, unit_id=target["unit_id"], limit=20
                )["page"]
                self.assertLessEqual(len(canonical_json_bytes(page)), 2 * 1024 * 1024)
                self.assertNotIn("unit", page)
                self.assertEqual(page["locator"]["unit_id"], target["unit_id"])
                self.assertEqual(page["target_ordinal"], target_ordinal)
                self.assertEqual(page["units"][0]["unit_id"], target["unit_id"])
                self.assertEqual(page["units"][0]["ordinal"], target_ordinal)
                for unit in page["units"]:
                    self.assertEqual(
                        "".join(segment["text"] for segment in unit["segments"]),
                        blocks[unit["ordinal"]],
                    )
                self.assertTrue(page["units"])

    # -- groups ---------------------------------------------------------

    def test_groups_keep_identity_across_pages(self) -> None:
        with self._connect_ready() as conn:
            fixture = self._single_source_stream(
                conn, label="a", blocks=[f"正文{index}。" for index in range(5)], group_size=3
            )
            stream_id = fixture["stream_id"]

            first = reader_streams.stream_units(conn, stream_id=stream_id, limit=2)
            first_page = first["page"]
            self.assertEqual(
                first_page["group_continuation"],
                {
                    "group_id": fixture["stream"]["units"][0]["group_id"],
                    "continues_previous": False,
                },
            )
            second = reader_streams.stream_units(
                conn, stream_id=stream_id, limit=2, cursor=first_page["next_cursor"]
            )
            second_page = second["page"]
            first_unit = second_page["units"][0]
            last_of_previous = first_page["units"][-1]
            self.assertEqual(first_unit["group_id"], last_of_previous["group_id"])
            self.assertTrue(first_unit["continues_previous"])
            self.assertEqual(
                second_page["group_continuation"],
                {"group_id": first_unit["group_id"], "continues_previous": True},
            )
            self.assertEqual(reading_contract.reading_response_errors("stream_page", second_page), [])

            groups = reader_streams.stream_groups(conn, stream_id=stream_id, limit=1)
            group_page = groups["page"]
            first_group = group_page["groups"][0]
            self.assertEqual(reading_contract.reading_response_errors("time_group", first_group), [])
            self.assertEqual(
                first_group["first_locator"]["unit_id"], fixture["stream"]["units"][0]["unit_id"]
            )
            self.assertEqual(
                first_group["last_locator"]["unit_id"], fixture["stream"]["units"][2]["unit_id"]
            )
            self.assertTrue(group_page["has_next"])
            next_groups = reader_streams.stream_groups(
                conn, stream_id=stream_id, limit=1, cursor=group_page["next_cursor"]
            )
            second_group = next_groups["page"]["groups"][0]
            self.assertEqual(second_group["ordinal"], 1)
            self.assertEqual(
                second_group["first_locator"]["unit_id"],
                fixture["stream"]["units"][3]["unit_id"],
            )
            self.assertTrue(next_groups["page"]["has_previous"])

    def test_cross_chapter_and_unknown_time_axis(self) -> None:
        with self._connect_ready() as conn:
            catalog = self._seed_catalog(conn, label="x")
            document_id = control_plane.create_document(conn, title="甲书")
            ctx_1 = self._seed_chapter(
                conn,
                document_id=document_id,
                label="c1",
                title="甲书",
                blocks=["一章一。", "一章二。"],
                catalog_sha=catalog,
                chapter_index=0,
            )
            ctx_2 = self._seed_chapter(
                conn,
                document_id=document_id,
                label="c2",
                title="甲书",
                blocks=["二章一。", "二章二。"],
                catalog_sha=catalog,
                chapter_index=1,
                revision_id=ctx_1["revision_id"],
            )
            stream = self._build_stream(
                ctx_1,
                catalog_sha=catalog,
                extra_ctxs=[ctx_2],
                group_plan=[
                    {
                        "key": "g0",
                        "first": 0,
                        "last": 0,
                        "year_key": "gregorian:208",
                        "period_key": "gregorian:208",
                        "year_label": "208年",
                        "period_label": "（月份未明确）",
                        "precision": "year",
                    },
                    {
                        "key": "g1",
                        "first": 1,
                        "last": 1,
                        "year_key": "gregorian:209",
                        "period_key": "gregorian:209",
                        "year_label": "209年",
                        "period_label": "（月份未明确）",
                        "precision": "year",
                    },
                    {
                        "key": "g2",
                        "first": 2,
                        "last": 3,
                        "mode": "unknown",
                        "status": "unknown",
                        "year_key": "unknown",
                        "period_key": "unknown",
                        "year_label": None,
                        "period_label": "时间未明确",
                        "precision": "unknown",
                    },
                ],
            )
            stream_id = self._publish(conn, stream)

            detail = reader_streams.stream_detail(conn, stream_id=stream_id)["page"]
            self.assertEqual(detail["unit_count"], 4)
            self.assertEqual(len(detail["chapters"]), 2)
            self.assertEqual(
                [chapter["chapter_id"] for chapter in detail["chapters"]],
                [ctx_1["chapter_id"], ctx_2["chapter_id"]],
            )

            page = reader_streams.stream_units(conn, stream_id=stream_id, limit=50)["page"]
            self.assertEqual([unit["ordinal"] for unit in page["units"]], [0, 1, 2, 3])
            self.assertEqual(page["units"][1]["chapter_id"], ctx_1["chapter_id"])
            self.assertEqual(page["units"][2]["chapter_id"], ctx_2["chapter_id"])

            group_page = reader_streams.stream_groups(
                conn, stream_id=stream_id, limit=50
            )["page"]
            self.assertEqual(
                [group["precision"] for group in group_page["groups"]],
                ["year", "year", "unknown"],
            )
            unknown = group_page["groups"][2]
            self.assertEqual(unknown["period_label"], "时间未明确")
            self.assertEqual(
                unknown["first_locator"]["unit_id"], stream["units"][2]["unit_id"]
            )
            self.assertEqual(
                unknown["last_locator"]["unit_id"], stream["units"][3]["unit_id"]
            )
            self.assertEqual(reading_contract.reading_response_errors("time_group", unknown), [])
            self.assertFalse(group_page["has_next"])

    # -- cursor rejection -----------------------------------------------

    def test_cursor_scope_snapshot_stream_and_direction_are_bound(self) -> None:
        with self._connect_ready() as conn:
            document_id = control_plane.create_document(conn, title="甲书")
            catalog_1 = self._seed_catalog(conn, label="a")
            catalog_2 = self._seed_catalog(conn, label="b")
            ctx_a = self._seed_chapter(
                conn,
                document_id=document_id,
                label="a",
                title="甲书",
                blocks=["甲一。", "甲二。", "甲三。"],
                catalog_sha=catalog_1,
            )
            stream_a = self._publish(conn, self._build_stream(ctx_a, catalog_sha=catalog_1))
            ctx_b = self._seed_chapter(
                conn,
                document_id=control_plane.create_document(conn, title="乙书"),
                label="b",
                title="乙书",
                blocks=["乙一。", "乙二。"],
                catalog_sha=catalog_1,
            )
            stream_b = self._publish(conn, self._build_stream(ctx_b, catalog_sha=catalog_1))

            page = reader_streams.stream_units(
                conn, stream_id=stream_a, catalog_sha=catalog_2, limit=1
            )["page"]
            next_cursor = page["next_cursor"]
            second = reader_streams.stream_units(
                conn, stream_id=stream_a, catalog_sha=catalog_2, limit=1, cursor=next_cursor
            )["page"]
            prev_cursor = second["prev_cursor"]
            self.assertIsNotNone(prev_cursor)

            # Another stream is rejected before any read.
            with self.assertRaises(reader_streams.ReadingStreamBadRequest):
                reader_streams.stream_units(
                    conn, stream_id=stream_b, catalog_sha=catalog_2, cursor=next_cursor
                )
            # Another snapshot is rejected.
            with self.assertRaises(reader_streams.ReadingStreamBadRequest):
                reader_streams.stream_units(
                    conn, stream_id=stream_a, catalog_sha=catalog_1, cursor=next_cursor
                )
            # A cursor from the other direction is rejected when the request
            # already committed to one.
            with self.assertRaises(reader_streams.ReadingStreamBadRequest):
                reader_streams.stream_units(
                    conn,
                    stream_id=stream_a,
                    catalog_sha=catalog_2,
                    cursor=prev_cursor,
                    direction="forward",
                )
            with self.assertRaises(reader_streams.ReadingStreamBadRequest):
                reader_streams.decode_unit_cursor(
                    prev_cursor,
                    stream_id=str(stream_a),
                    catalog_sha=catalog_2,
                    expected_kind="next",
                )
            with self.assertRaises(reader_streams.ReadingStreamBadRequest):
                reader_streams.decode_unit_cursor("not-a-cursor", stream_id=str(stream_a), catalog_sha=catalog_2)

    # -- visibility / no drift / read-only ------------------------------

    def test_old_stream_keeps_text_and_hides_new_unit(self) -> None:
        with self._connect_ready() as conn:
            document_id = control_plane.create_document(conn, title="甲书")
            catalog_1 = self._seed_catalog(conn, label="a")
            ctx_old = self._seed_chapter(
                conn,
                document_id=document_id,
                label="v1",
                title="甲书",
                blocks=["旧文本一。", "旧文本二。"],
                catalog_sha=catalog_1,
            )
            old_stream = self._publish(conn, self._build_stream(ctx_old, catalog_sha=catalog_1))

            catalog_2 = self._seed_catalog(conn, label="b")
            ctx_new = self._seed_chapter(
                conn,
                document_id=document_id,
                label="v2",
                title="甲书",
                blocks=["新文本一。"],
                catalog_sha=catalog_2,
            )
            new_stream = self._publish(conn, self._build_stream(ctx_new, catalog_sha=catalog_2))
            self.assertNotEqual(old_stream, new_stream)

            # The old snapshot cannot open the new stream at all.
            for call in (
                lambda: reader_streams.stream_detail(
                    conn, stream_id=new_stream, catalog_sha=catalog_1
                ),
                lambda: reader_streams.stream_units(
                    conn, stream_id=new_stream, catalog_sha=catalog_1
                ),
                lambda: reader_streams.locate_unit(
                    conn,
                    stream_id=new_stream,
                    unit_id="ru_" + "0" * 24,
                    catalog_sha=catalog_1,
                ),
            ):
                with self.assertRaises(reader_streams.ReadingStreamNotFound):
                    call()

            # The old stream still serves its own old text under a newer
            # snapshot; the new revision never rewrites it.
            page = reader_streams.stream_units(
                conn, stream_id=old_stream, catalog_sha=catalog_2, limit=10
            )["page"]
            texts = ["".join(seg["text"] for seg in unit["segments"]) for unit in page["units"]]
            self.assertEqual(texts, ["旧文本一。", "旧文本二。"])

            # Unknown / cross-stream units are invisible.
            with self.assertRaises(reader_streams.ReadingStreamNotFound):
                reader_streams.locate_unit(
                    conn, stream_id=old_stream, unit_id="ru_" + "f" * 24
                )
            new_unit_id = self._build_stream(ctx_new, catalog_sha=catalog_2)["units"][0]["unit_id"]
            with self.assertRaises(reader_streams.ReadingStreamNotFound):
                reader_streams.locate_unit(conn, stream_id=old_stream, unit_id=new_unit_id)
            with self.assertRaises(reader_streams.ReadingStreamNotFound):
                reader_streams.stream_detail(conn, stream_id=_uuid7())

    def test_get_paths_are_read_only(self) -> None:
        with self._connect_ready() as conn:
            fixture = self._single_source_stream(
                conn, label="a", blocks=[f"正文{index}。" for index in range(4)], group_size=2
            )
            stream_id = fixture["stream_id"]
            target = fixture["stream"]["units"][3]

            conn.commit()
            conn.read_only = True
            try:
                reader_streams.list_streams(conn)
                reader_streams.stream_detail(conn, stream_id=stream_id)
                reader_streams.stream_units(conn, stream_id=stream_id, limit=2)
                reader_streams.stream_groups(conn, stream_id=stream_id, limit=2)
                reader_streams.locate_unit(conn, stream_id=stream_id, unit_id=target["unit_id"])
            finally:
                conn.rollback()
                conn.read_only = False

    # -- detail ----------------------------------------------------------

    def test_stream_detail_exposes_directory_without_body(self) -> None:
        with self._connect_ready() as conn:
            fixture = self._single_source_stream(
                conn, label="a", blocks=["一。", "二。", "三。"], group_size=2
            )
            envelope = reader_streams.stream_detail(conn, stream_id=fixture["stream_id"])
            page = envelope["page"]
            self.assertEqual(page["stream_id"], str(fixture["stream_id"]))
            self.assertEqual(page["unit_count"], 3)
            self.assertEqual(page["group_count"], 2)
            self.assertEqual(page["title"], "a书")
            self.assertEqual(len(page["chapters"]), 1)
            self.assertNotIn("units", page)
            self.assertEqual(page["chapters"][0]["unit_count"], 3)
            self.assertEqual(
                page["start_locator"]["unit_id"], fixture["stream"]["units"][0]["unit_id"]
            )


if __name__ == "__main__":
    unittest.main()
