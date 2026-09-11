"""PostgreSQL 18 integration tests for the Chronicle C2-R2-T05 reading store.

Covers ``continuous-reading.md`` sections 4-5: fresh migration + reapply,
immutable stream/unit/group/occurrence write and read, idempotent replay,
manifest conflict, caller rollback with no residue, wrong
publication/unit/ref rejection, unique constraints, ordinal and group keyset
pagination, event reverse lookup, snapshot visibility (an old catalog never
sees a later representation or stream, even for the same canonical id), and
concurrent same-revision publishes.

Fixtures seed *two sources*, *multiple revisions* and *multiple catalogs* so
the snapshot rules have something real to discriminate. The seed path is an
explicit test loading path (direct control-plane/chapter-row inserts), not a
second production success path; the production write path is T06's single
publish transaction calling :func:`reading_store.persist_reading_stream`.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import threading
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import canonical_store
import control_plane
import reading_contract
import reading_store
from common import PersistenceConflict, PersistenceError
from migrations import apply_migrations

DEFAULT_CONTROL_URL = "postgresql://loom:loom@127.0.0.1:15432/loom_control"

_UUID_COUNTER = [1000]


def _uuid7() -> str:
    """Deterministic-but-unique RFC 9562 UUIDv7 for fixtures."""
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


class ReadingStorePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_t05_test_{uuid.uuid4().hex}"
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

    def _seed_source(
        self, conn, *, label: str, title: str, blocks: list[str], catalog_sha: str
    ) -> dict:
        """Create a document/revision/job and one published chapter.

        Direct chapter-row inserts keep the test fixture explicit; the
        immutable reading store still reads the real first-round
        ``chapter_publications`` row for the body.
        """
        document_id = control_plane.create_document(conn, title=title)
        revision_id, revision_no = control_plane.create_revision(
            conn,
            document_id=document_id,
            source_sha256=_sha256(f"{label}-source"),
            source_bytes=len("".join(blocks).encode("utf-8")),
            source_media_type="text/markdown",
        )
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
        chapter_id = f"ch_{label}"
        artifact_sha256 = _sha256(f"{label}-artifact")
        blocks_payload = [
            {"block_id": f"t_{index:03d}", "text": text}
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
                0,
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
            "chapter_index": 0,
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

    def _seed_bundle_events(self, conn, *refs: tuple[str, str]) -> None:
        for bundle, ref in refs:
            conn.execute(
                """
                INSERT INTO chronicle.source_bundles(
                    bundle_label, schema_version, source_ref, source_title,
                    artifact_sha256, source_payload, bundle_payload
                ) VALUES (%s, '0.1', %s, 'T', %s, '{}', '{}')
                ON CONFLICT (bundle_label) DO NOTHING
                """,
                (bundle, f"src_{bundle}", _sha256(f"bundle-{bundle}")),
            )
            conn.execute(
                """
                INSERT INTO chronicle.staged_events(
                    bundle_label, record_ref, payload_sha256, payload
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT (bundle_label, record_ref) DO NOTHING
                """,
                (bundle, ref, _sha256(f"{bundle}:{ref}"), json.dumps({"temp_id": ref})),
            )

    def _seed_catalog(self, conn, *, events: list[tuple[str, list[tuple[str, str]]]]) -> str:
        self._seed_bundle_events(
            conn, *[ref for _, refs in events for ref in refs]
        )
        catalog = {
            "schema": "chronicle.canonical-catalog",
            "version": "0.1",
            "canonical_entities": [],
            "canonical_events": [
                {
                    "canonical_id": canonical_id,
                    "representations": [
                        {"bundle": bundle, "ref": ref} for bundle, ref in refs
                    ],
                }
                for canonical_id, refs in events
            ],
            "event_relations": [],
            "warnings": [],
        }
        catalog_sha, _ = canonical_store.persist_catalog(conn, catalog)
        return catalog_sha

    def _build_stream(
        self,
        ctx: dict,
        *,
        catalog_sha: str,
        occurrences: list[dict] | None = None,
        groups: list[dict] | None = None,
        tag: str = "v1",
    ) -> dict:
        """Build a compiled reading stream for one source context."""
        occurrence_by_unit: dict[int, list[dict]] = {}
        for occurrence in occurrences or []:
            occurrence_by_unit.setdefault(occurrence["unit_index"], []).append(occurrence)

        units: list[dict] = []
        for index, block in enumerate(ctx["blocks"]):
            unit_id = f"ru_{ctx['label']}_{index}"
            text = block["text"]
            units.append(
                {
                    "unit_id": unit_id,
                    "ordinal": index,
                    "publication_id": str(ctx["publication_id"]),
                    "artifact_sha256": ctx["artifact_sha256"],
                    "chapter_id": ctx["chapter_id"],
                    "block_id": block["block_id"],
                    "text_hash": _sha256(text),
                    "narrative_time": {
                        "mode": "events",
                        "status": "resolved",
                        "event_refs": [],
                        "from_block_id": None,
                        "observations": [],
                        "year_key": f"gregorian:{208 + index}",
                        "period_key": f"gregorian:{208 + index}",
                        "year_label": f"{208 + index}年",
                        "period_label": "（月份未明确）",
                        "precision": "year",
                        "continues_previous": False,
                    },
                    "segments": [{"kind": "text", "text": text}],
                    "context_entities": [],
                    "source_anchor_ids": [f"anc_{block['block_id']}"],
                    "group_id": f"tg_{ctx['label']}_{index}",
                    "continues_previous": False,
                    "event_occurrences": occurrence_by_unit.get(index, []),
                }
            )

        unit_groups = groups or [
            {
                "ordinal": index,
                "group_id": unit["group_id"],
                "first_unit_ordinal": index,
                "last_unit_ordinal": index,
                "unit_count": 1,
                "year_key": unit["narrative_time"]["year_key"],
                "period_key": unit["narrative_time"]["period_key"],
                "year_label": unit["narrative_time"]["year_label"],
                "period_label": unit["narrative_time"]["period_label"],
                "precision": "year",
                "observations": [],
                "continues_previous": False,
            }
            for index, unit in enumerate(units)
        ]
        for group in unit_groups:
            group.setdefault("first_unit_id", units[group["first_unit_ordinal"]]["unit_id"])
            group.setdefault("last_unit_id", units[group["last_unit_ordinal"]]["unit_id"])
            group.setdefault(
                "unit_count", group["last_unit_ordinal"] - group["first_unit_ordinal"] + 1
            )

        flat_occurrences = [
            {
                "unit_id": units[occurrence["unit_index"]]["unit_id"],
                "event_kind": occurrence["event_kind"],
                "span_id": occurrence.get("span_id"),
                "canonical_event_id": occurrence["canonical_event_id"],
                "relation": occurrence["relation"],
                "bundle_label": occurrence["bundle_label"],
                "record_ref": occurrence["record_ref"],
            }
            for occurrence in occurrences or []
        ]

        manifest = {
            "schema": "chronicle.reading-stream",
            "version": "0.1",
            "tag": tag,
            "revision_id": str(ctx["revision_id"]),
            "catalog_sha256": catalog_sha,
            "unit_ids": [unit["unit_id"] for unit in units],
            "group_ids": [group["group_id"] for group in unit_groups],
        }
        return {
            "revision_id": str(ctx["revision_id"]),
            "document_id": str(ctx["document_id"]),
            "origin_catalog_sha": catalog_sha,
            "manifest": manifest,
            "chapter_publication_ids": [str(ctx["publication_id"])],
            "units": units,
            "groups": unit_groups,
            "event_occurrences": flat_occurrences,
        }

    def _source_with_catalog(
        self,
        conn,
        *,
        label: str,
        title: str,
        blocks: list[str],
        events: list[tuple[str, list[tuple[str, str]]]],
    ) -> tuple[dict, str]:
        catalog_sha = self._seed_catalog(conn, events=events)
        ctx = self._seed_source(
            conn, label=label, title=title, blocks=blocks, catalog_sha=catalog_sha
        )
        return ctx, catalog_sha

    # -- migration -----------------------------------------------------

    def test_fresh_migrate_reapply_and_tables(self) -> None:
        with self._connect_ready() as conn:
            apply_migrations(conn)  # reapply is a no-op
            names = {row[0] for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'chronicle'")}
            for table in (
                "reading_streams",
                "reading_units",
                "reading_time_groups",
                "reading_event_occurrences",
            ):
                self.assertIn(table, names)
            versions = [row[0] for row in conn.execute(
                "SELECT version FROM chronicle.schema_migrations ORDER BY version")]
            self.assertIn("0007_chronicle_reading_streams.sql", versions)
            triggers = {row[0] for row in conn.execute(
                "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"
                " AND tgrelid::regclass::text LIKE 'chronicle.reading%'")}
            self.assertIn("forbid_reading_stream_mutation", triggers)
            self.assertIn("enforce_reading_occurrence_membership", triggers)

    # -- write/read round-trip -----------------------------------------

    def test_persist_and_read_roundtrip(self) -> None:
        with self._connect_ready() as conn:
            event_id = _uuid7()
            ctx_a, catalog_a = self._source_with_catalog(
                conn,
                label="a",
                title="甲书",
                blocks=["建安十三年，曹操南下。", "赤壁之战爆发。"],
                events=[(event_id, [("src-a", "evt_001")])],
            )
            with conn.transaction():
                stream = self._build_stream(
                    ctx_a,
                    catalog_sha=catalog_a,
                    occurrences=[
                        {
                            "unit_index": 1,
                            "event_kind": "span",
                            "span_id": "sp_001",
                            "canonical_event_id": event_id,
                            "relation": "current",
                            "bundle_label": "src-a",
                            "record_ref": "evt_001",
                        }
                    ],
                    groups=[
                        {
                            "ordinal": 0,
                            "group_id": "tg_a_0",
                            "first_unit_ordinal": 0,
                            "last_unit_ordinal": 0,
                            "unit_count": 1,
                            "year_key": "gregorian:208",
                            "period_key": "gregorian:208",
                            "year_label": "208年",
                            "period_label": "（月份未明确）",
                            "precision": "year",
                            "observations": [],
                            "continues_previous": False,
                        },
                        {
                            "ordinal": 1,
                            "group_id": "tg_a_1",
                            "first_unit_ordinal": 1,
                            "last_unit_ordinal": 1,
                            "unit_count": 1,
                            "year_key": "gregorian:209",
                            "period_key": "gregorian:209",
                            "year_label": "209年",
                            "period_label": "（月份未明确）",
                            "precision": "year",
                            "observations": [],
                            "continues_previous": False,
                        },
                    ],
                )
                stream_id = reading_store.persist_reading_stream(conn, stream)
            reading_contract  # noqa: B018 - imported for contract parity
            from common import parse_uuid7
            parse_uuid7(str(stream_id), "stream_id")

            detail = reading_store.read_reading_stream(conn, stream_id=stream_id)
            self.assertEqual(detail["revision_id"], str(ctx_a["revision_id"]))
            self.assertEqual(detail["unit_count"], 2)
            self.assertEqual(detail["group_count"], 2)
            self.assertEqual(detail["chapter_publication_ids"], [str(ctx_a["publication_id"])])

            page = reading_store.read_reading_units(conn, stream_id=stream_id, limit=10)
            self.assertEqual([u["ordinal"] for u in page["items"]], [0, 1])
            self.assertEqual(page["items"][1]["block_id"], "t_002")
            self.assertFalse(page["has_more"])

            groups = reading_store.read_reading_groups(conn, stream_id=stream_id, limit=10)
            self.assertEqual([g["group_id"] for g in groups["items"]], ["tg_a_0", "tg_a_1"])

            events = reading_store.read_event_occurrences(
                conn, snapshot_catalog_sha=catalog_a, canonical_event_id=event_id
            )
            self.assertEqual(len(events["items"]), 1)
            self.assertEqual(events["items"][0]["unit_id"], "ru_a_1")
            self.assertEqual(events["items"][0]["span_id"], "sp_001")

    # -- idempotency / conflict ----------------------------------------

    def test_idempotent_replay_and_manifest_conflict(self) -> None:
        with self._connect_ready() as conn:
            event_id = _uuid7()
            ctx, catalog = self._source_with_catalog(
                conn,
                label="a",
                title="甲书",
                blocks=["正文一。"],
                events=[(event_id, [("src-a", "evt_001")])],
            )
            stream = self._build_stream(ctx, catalog_sha=catalog, tag="v1")
            with conn.transaction():
                first = reading_store.persist_reading_stream(conn, stream)
            with conn.transaction():
                second = reading_store.persist_reading_stream(conn, stream)
            self.assertEqual(first, second)
            self.assertEqual(
                conn.execute("SELECT count(*) FROM chronicle.reading_streams").fetchone()[0], 1
            )
            self.assertEqual(
                conn.execute("SELECT count(*) FROM chronicle.reading_units").fetchone()[0], 1
            )
            conflict = self._build_stream(ctx, catalog_sha=catalog, tag="v2")
            with self.assertRaises(PersistenceConflict):
                with conn.transaction():
                    reading_store.persist_reading_stream(conn, conflict)
            self.assertEqual(
                conn.execute("SELECT count(*) FROM chronicle.reading_streams").fetchone()[0], 1
            )

    def test_caller_rollback_leaves_no_rows(self) -> None:
        with self._connect_ready() as conn:
            event_id = _uuid7()
            ctx, catalog = self._source_with_catalog(
                conn,
                label="a",
                title="甲书",
                blocks=["正文一。"],
                events=[(event_id, [("src-a", "evt_001")])],
            )
            stream = self._build_stream(ctx, catalog_sha=catalog)
            with self.assertRaises(RuntimeError):
                with conn.transaction():
                    reading_store.persist_reading_stream(conn, stream)
                    raise RuntimeError("caller aborts the publish transaction")
            for table in (
                "reading_streams",
                "reading_units",
                "reading_time_groups",
                "reading_event_occurrences",
            ):
                self.assertEqual(
                    conn.execute(f"SELECT count(*) FROM chronicle.{table}").fetchone()[0],
                    0,
                    table,
                )

    # -- rejected references -------------------------------------------

    def test_cross_revision_publication_rejected(self) -> None:
        with self._connect_ready() as conn:
            event_id = _uuid7()
            ctx_a, catalog_a = self._source_with_catalog(
                conn,
                label="a",
                title="甲书",
                blocks=["正文一。"],
                events=[(event_id, [("src-a", "evt_001")])],
            )
            ctx_b, _ = self._source_with_catalog(
                conn,
                label="b",
                title="乙书",
                blocks=["别的正文。"],
                events=[(event_id, [("src-a", "evt_001")])],
            )
            stream = self._build_stream(ctx_a, catalog_sha=catalog_a)
            # Cite B's publication while claiming A's revision.
            stream["chapter_publication_ids"] = [str(ctx_b["publication_id"])]
            stream["units"][0]["publication_id"] = str(ctx_b["publication_id"])
            stream["units"][0]["artifact_sha256"] = ctx_b["artifact_sha256"]
            stream["units"][0]["chapter_id"] = ctx_b["chapter_id"]
            with self.assertRaises(PersistenceConflict):
                with conn.transaction():
                    reading_store.persist_reading_stream(conn, stream)
            self.assertEqual(
                conn.execute("SELECT count(*) FROM chronicle.reading_streams").fetchone()[0], 0
            )

    def test_unknown_block_rejected(self) -> None:
        with self._connect_ready() as conn:
            event_id = _uuid7()
            ctx, catalog = self._source_with_catalog(
                conn,
                label="a",
                title="甲书",
                blocks=["正文一。"],
                events=[(event_id, [("src-a", "evt_001")])],
            )
            stream = self._build_stream(ctx, catalog_sha=catalog)
            stream["units"][0]["block_id"] = "t_999"
            with self.assertRaises(PersistenceConflict):
                with conn.transaction():
                    reading_store.persist_reading_stream(conn, stream)

    def test_occurrence_outside_snapshot_rejected(self) -> None:
        with self._connect_ready() as conn:
            event_id = _uuid7()
            ctx, catalog = self._source_with_catalog(
                conn,
                label="a",
                title="甲书",
                blocks=["正文一。"],
                events=[(event_id, [("src-a", "evt_001")])],
            )
            stream = self._build_stream(
                ctx,
                catalog_sha=catalog,
                occurrences=[
                    {
                        "unit_index": 0,
                        "event_kind": "current",
                        "canonical_event_id": event_id,
                        "relation": "current",
                        "bundle_label": "src-a",
                        "record_ref": "evt_999",
                    }
                ],
            )
            with self.assertRaises(PersistenceConflict):
                with conn.transaction():
                    reading_store.persist_reading_stream(conn, stream)

    # -- uniqueness / immutability -------------------------------------

    def test_unique_constraints_and_immutability(self) -> None:
        with self._connect_ready() as conn:
            event_id = _uuid7()
            ctx_a, catalog_a = self._source_with_catalog(
                conn,
                label="a",
                title="甲书",
                blocks=["正文一。"],
                events=[(event_id, [("src-a", "evt_001")])],
            )
            ctx_b, _ = self._source_with_catalog(
                conn,
                label="b",
                title="乙书",
                blocks=["别的正文。"],
                events=[(event_id, [("src-a", "evt_001")])],
            )
            with conn.transaction():
                stream_id = reading_store.persist_reading_stream(
                    conn, self._build_stream(ctx_a, catalog_sha=catalog_a)
                )
            # Same unit_id in a different stream is a global unique violation.
            clash = self._build_stream(ctx_b, catalog_sha=catalog_a)
            clash["units"][0]["unit_id"] = "ru_a_0"
            clash["groups"][0]["first_unit_id"] = "ru_a_0"
            clash["groups"][0]["last_unit_id"] = "ru_a_0"
            with self.assertRaises(PersistenceConflict):
                with conn.transaction():
                    reading_store.persist_reading_stream(conn, clash)
            # Reading rows are append-only.
            with self.assertRaises(Exception):
                with conn.transaction():
                    conn.execute(
                        "UPDATE chronicle.reading_streams SET manifest = '{}'::jsonb"
                        " WHERE stream_id = %s",
                        (stream_id,),
                    )
            with self.assertRaises(Exception):
                with conn.transaction():
                    conn.execute(
                        "DELETE FROM chronicle.reading_units WHERE stream_id = %s",
                        (stream_id,),
                    )

    # -- pagination ----------------------------------------------------

    def test_ordinal_and_group_keyset_pagination(self) -> None:
        with self._connect_ready() as conn:
            event_id = _uuid7()
            ctx, catalog = self._source_with_catalog(
                conn,
                label="a",
                title="甲书",
                blocks=[f"正文{index}。" for index in range(5)],
                events=[(event_id, [("src-a", "evt_001")])],
            )
            with conn.transaction():
                stream_id = reading_store.persist_reading_stream(
                    conn, self._build_stream(ctx, catalog_sha=catalog)
                )
            first = reading_store.read_reading_units(
                conn, stream_id=stream_id, limit=2
            )
            self.assertEqual([u["ordinal"] for u in first["items"]], [0, 1])
            self.assertTrue(first["has_more"])
            second = reading_store.read_reading_units(
                conn, stream_id=stream_id, limit=2, after_ordinal=1
            )
            self.assertEqual([u["ordinal"] for u in second["items"]], [2, 3])
            self.assertTrue(second["has_more"])
            backward = reading_store.read_reading_units(
                conn, stream_id=stream_id, limit=2, before_ordinal=3
            )
            self.assertEqual([u["ordinal"] for u in backward["items"]], [1, 2])
            self.assertTrue(backward["has_more"])

            groups = reading_store.read_reading_groups(
                conn, stream_id=stream_id, limit=3
            )
            self.assertEqual(len(groups["items"]), 3)
            self.assertTrue(groups["has_more"])

    # -- event reverse lookup / snapshot -------------------------------

    def test_snapshot_visibility_excludes_future_stream_and_representation(self) -> None:
        with self._connect_ready() as conn:
            event_id = _uuid7()
            # C1 lists only the A representation; C2 adds B's.
            catalog_1 = self._seed_catalog(
                conn, events=[(event_id, [("src-a", "evt_001")])]
            )
            ctx_a = self._seed_source(
                conn, label="a", title="甲书", blocks=["甲书正文。"], catalog_sha=catalog_1
            )
            catalog_2 = self._seed_catalog(
                conn,
                events=[(event_id, [("src-a", "evt_001"), ("src-b", "evt_002")])],
            )
            ctx_b = self._seed_source(
                conn, label="b", title="乙书", blocks=["乙书正文。"], catalog_sha=catalog_2
            )
            stream_a = self._build_stream(
                ctx_a,
                catalog_sha=catalog_1,
                occurrences=[
                    {
                        "unit_index": 0,
                        "event_kind": "span",
                        "span_id": "sp_a",
                        "canonical_event_id": event_id,
                        "relation": "current",
                        "bundle_label": "src-a",
                        "record_ref": "evt_001",
                    }
                ],
            )
            stream_b = self._build_stream(
                ctx_b,
                catalog_sha=catalog_2,
                occurrences=[
                    {
                        "unit_index": 0,
                        "event_kind": "span",
                        "span_id": "sp_b",
                        "canonical_event_id": event_id,
                        "relation": "current",
                        "bundle_label": "src-b",
                        "record_ref": "evt_002",
                    }
                ],
            )
            with conn.transaction():
                stream_a_id = reading_store.persist_reading_stream(conn, stream_a)
                stream_b_id = reading_store.persist_reading_stream(conn, stream_b)

            old_snapshot = reading_store.list_reading_streams(
                conn, snapshot_catalog_sha=catalog_1
            )
            self.assertEqual(
                [item["stream_id"] for item in old_snapshot["items"]], [str(stream_a_id)]
            )
            new_snapshot = reading_store.list_reading_streams(
                conn, snapshot_catalog_sha=catalog_2
            )
            self.assertEqual(
                sorted(item["stream_id"] for item in new_snapshot["items"]),
                sorted([str(stream_a_id), str(stream_b_id)]),
            )

            # Same canonical id, but the old snapshot must not see B's later
            # representation or stream.
            old_events = reading_store.read_event_occurrences(
                conn, snapshot_catalog_sha=catalog_1, canonical_event_id=event_id
            )
            self.assertEqual(len(old_events["items"]), 1)
            self.assertEqual(old_events["items"][0]["stream_id"], str(stream_a_id))
            new_events = reading_store.read_event_occurrences(
                conn, snapshot_catalog_sha=catalog_2, canonical_event_id=event_id
            )
            self.assertEqual(len(new_events["items"]), 2)

            # The old snapshot also cannot open the later stream at all.
            with self.assertRaises(PersistenceError):
                reading_store.read_reading_stream(
                    conn, stream_id=stream_b_id, snapshot_catalog_sha=catalog_1
                )
            with self.assertRaises(PersistenceError):
                reading_store.read_reading_stream(
                    conn, stream_id=stream_b_id, snapshot_catalog_sha="0" * 64
                )

    # -- concurrency ---------------------------------------------------

    def test_concurrent_same_revision_publish(self) -> None:
        with self._connect_ready() as conn:
            event_id = _uuid7()
            ctx, catalog = self._source_with_catalog(
                conn,
                label="a",
                title="甲书",
                blocks=["正文一。"],
                events=[(event_id, [("src-a", "evt_001")])],
            )
            same = self._build_stream(ctx, catalog_sha=catalog, tag="same")
        barrier = threading.Barrier(2)
        outcomes: list = [None, None]

        def _publish(index: int, stream: dict) -> None:
            try:
                with psycopg.connect(self.database_url) as conn:
                    barrier.wait(timeout=60)
                    outcomes[index] = reading_store.persist_reading_stream(conn, stream)
            except Exception as exc:  # captured, asserted below
                outcomes[index] = exc

        threads = [
            threading.Thread(target=_publish, args=(0, same)),
            threading.Thread(target=_publish, args=(1, same)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
            self.assertFalse(thread.is_alive(), "publish thread hung")
        self.assertEqual(outcomes[0], outcomes[1])
        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(
                conn.execute("SELECT count(*) FROM chronicle.reading_streams").fetchone()[0], 1
            )

        # Different bytes for a fresh revision: exactly one publisher survives.
        with psycopg.connect(self.database_url) as conn:
            ctx_race, catalog_race = self._source_with_catalog(
                conn,
                label="c",
                title="丙书",
                blocks=["丙书正文。"],
                events=[(event_id, [("src-a", "evt_001")])],
            )
            winner = self._build_stream(ctx_race, catalog_sha=catalog_race, tag="winner")
            loser = self._build_stream(ctx_race, catalog_sha=catalog_race, tag="loser")
        barrier = threading.Barrier(2)
        outcomes = [None, None]

        def _race(index: int, stream: dict) -> None:
            try:
                with psycopg.connect(self.database_url) as conn:
                    barrier.wait(timeout=60)
                    reading_store.persist_reading_stream(conn, stream)
                    outcomes[index] = "ok"
            except PersistenceConflict as exc:
                outcomes[index] = exc

        threads = [
            threading.Thread(target=_race, args=(0, winner)),
            threading.Thread(target=_race, args=(1, loser)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
            self.assertFalse(thread.is_alive(), "race thread hung")
        self.assertIn("ok", outcomes)
        self.assertTrue(any(isinstance(value, PersistenceConflict) for value in outcomes))
        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM chronicle.reading_streams WHERE revision_id = %s",
                    (ctx_race["revision_id"],),
                ).fetchone()[0],
                1,
            )


if __name__ == "__main__":
    unittest.main()
