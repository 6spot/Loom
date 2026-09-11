"""PostgreSQL 18 integration tests for the C2-R2-T06 reading publication wiring.

Proves the production chapter chain publishes the canonical catalog, every
complete chapter and the whole immutable reading index in one transaction:

- a fresh 0.2 revision flows through extract/assemble/resolve/publish/present
  and exposes exactly one reading stream whose units reassemble the published
  translation blocks and whose groups/occurrences are readable by the T05
  helpers;
- recompiling and replaying the same revision reuses the identical stream and
  unit IDs without any additional model call;
- a fault injected after the catalog, after the chapters, while writing the
  reading index and before the publish checkpoint leaves zero public content
  (no catalog, no chapter publication, no reading stream/unit/group/
  occurrence), and a clean retry then succeeds;
- a chapter plan whose content hashes drift from the accepted 0.2 artifacts is
  rejected fail-closed with no public rows.

The joint reading model is the explicit 0.2 fixture-pack test injection
(``FixtureReadingChapterModel``); production model selection is covered by
``test_reading_provider_unit.py``. The stream/event read APIs belong to
T07/T08 and are not fabricated here.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
for path in (str(HERE), str(PERSISTENCE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import canonical_store  # noqa: E402
import chapter_contract  # noqa: E402
import chapter_plan  # noqa: E402
import chapter_store  # noqa: E402
import control_plane  # noqa: E402
from common import PersistenceError  # noqa: E402
from migrations import apply_migrations  # noqa: E402

import chapter_stage as stage  # noqa: E402
import ingestion_worker as worker  # noqa: E402
import reading_projection as RP  # noqa: E402
import reading_store  # noqa: E402
import resolve_publish as R  # noqa: E402


DEFAULT_CONTROL_URL = "postgresql://loom:loom@127.0.0.1:15432/loom_control"
WORKER = "worker-t06"

TEXT_DISTINCT = """# 測試書

## 先主傳

劉備字玄德，涿郡涿縣人也。漢景帝子中山靖王勝之後也。備少孤，與母以織席販履為業。

## 周瑜傳

周瑜字公瑾，廬江舒人也。瑜長壯有姿貌，精音律，江東諺云曲有誤周郎顧。
"""


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
        cwd=HERE.parents[2],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    with psycopg.connect(url, connect_timeout=10):
        return url


def _database_conninfo(control_url: str, database_name: str) -> str:
    params = conninfo_to_dict(control_url)
    params["dbname"] = database_name
    return make_conninfo(**params)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _plan_for(text: str, revision_id: uuid.UUID, source_sha: str) -> dict:
    locator = {
        "revision_id": str(revision_id),
        "source_sha256": source_sha,
        "normalized_sha256": _sha256(text),
    }
    return chapter_plan.plan_chapters(
        text, locator, "liezhuan.md",
        limits=chapter_contract.ChapterLimits(),
    )


def _reading_specs() -> list[dict]:
    return [
        {
            "translation": "劉備，字玄德，乃漢室宗親，以織席販履為業。",
            "entities": [{"name": "劉備", "type": "person", "mention": "劉備"}],
            "event": {"type": "other", "title": "劉備織席販履"},
        },
        {
            "translation": "周瑜，字公瑾，姿貌雄偉，精通音律，時人稱之。",
            "entities": [{"name": "周瑜", "type": "person", "mention": "周瑜"}],
            "event": {"type": "cultural", "title": "周瑜顧曲"},
        },
    ]


def _pack_payload(plan: dict, revision_id: uuid.UUID, specs: list[dict]) -> dict:
    chapters = []
    for chapter, spec in zip(plan["chapters"], specs):
        chapters.append(
            {
                "chapter_id": chapter["chapter_id"],
                "revision_id": str(revision_id),
                "source_title": "測試書",
                "translation_text": spec["translation"],
                "entities": spec["entities"],
                "event": spec["event"],
                "predicate": "affected",
            }
        )
    return {
        "schema": "chronicle.chapter-fixture-pack",
        "version": "0.1",
        "model_version": "t06-reading-test",
        "chapters": chapters,
    }


def _load_reading_fixture_model(pack: dict):
    import fixture_model  # noqa: E402

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as handle:
        json.dump(pack, handle, ensure_ascii=False)
        path = handle.name
    try:
        return fixture_model.models_from_reading_chapter_fixture_pack(path)
    finally:
        os.unlink(path)


class CountingReadingModel:
    """0.2 fixture provider that counts how many model calls were issued."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.name = inner.name
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        return self.inner.complete(prompt)


class ReadingPipelinePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_t06_test_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            from psycopg import sql

            conn.execute(
                sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(self.database_name)
                )
            )
        self.database_url = _database_conninfo(
            self.control_url, self.database_name
        )
        with psycopg.connect(self.database_url) as conn:
            apply_migrations(conn)

    def tearDown(self) -> None:
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            from psycopg import sql

            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(self.database_name)
                )
            )

    # -- helpers --------------------------------------------------------

    def _queue_job(self, text: str):
        source_sha = _sha256(text)
        with psycopg.connect(self.database_url) as conn:
            document_id = control_plane.create_document(conn, title="測試書")
            revision_id, _ = control_plane.create_revision(
                conn, document_id=document_id,
                source_sha256=source_sha,
                source_bytes=len(text.encode("utf-8")),
                source_media_type="text/markdown",
                filename="liezhuan.md",
            )
            job_id = control_plane.queue_job(conn, revision_id=revision_id)
            conn.commit()
        return job_id, revision_id, source_sha

    def _prepare_model(self, text, revision_id, source_sha, specs=None):
        plan = _plan_for(text, revision_id, source_sha)
        pack = _pack_payload(plan, revision_id, specs or _reading_specs())
        return CountingReadingModel(_load_reading_fixture_model(pack)), plan

    def _run_once(self, job_id, text, source_sha, model, **kwargs):
        return worker.run_once(
            self.database_url, worker=WORKER,
            revision_source=lambda _job: (text, source_sha),
            chapter_model=model,
            chapter_limits=chapter_contract.ChapterLimits(),
            job_id=job_id, **kwargs,
        )

    def _reading_stream_row(self, revision_id):
        with psycopg.connect(self.database_url) as conn:
            return conn.execute(
                """
                SELECT stream_id, chapter_publication_ids, unit_count, group_count
                FROM chronicle.reading_streams WHERE revision_id = %s
                """,
                (revision_id,),
            ).fetchone()

    def _public_counts(self) -> dict[str, int]:
        tables = (
            "canonical_catalogs",
            "chapter_publications",
            "reading_streams",
            "reading_units",
            "reading_time_groups",
            "reading_event_occurrences",
        )
        with psycopg.connect(self.database_url) as conn:
            return {
                table: int(
                    conn.execute(
                        f"SELECT count(*) FROM chronicle.{table}"
                    ).fetchone()[0]
                )
                for table in tables
            }

    def _advance_running(self, job_id, *stages) -> None:
        with psycopg.connect(self.database_url) as conn:
            for stage_name in stages:
                control_plane.advance_stage(
                    conn, job_id=job_id, stage=stage_name, status="running"
                )
            conn.commit()

    def _run_to_publish(self, text: str):
        """Drive the chapter chain to a running publish stage (0.2 artifacts)."""
        job_id, revision_id, source_sha = self._queue_job(text)
        model, plan = self._prepare_model(text, revision_id, source_sha)
        with psycopg.connect(self.database_url) as conn:
            control_plane.claim_job(
                conn, worker=WORKER, lease_seconds=300, job_id=job_id
            )
            conn.commit()
        self._advance_running(
            job_id, "structure", "segment", "extract", "assemble", "resolve",
            "publish",
        )
        _, _, plan, requests = stage.load_chapter_inputs(
            self.database_url, job_id=job_id,
            revision_source=lambda _job: (text, source_sha),
            limits=chapter_contract.ChapterLimits(),
            candidate_version="0.2",
        )
        self.assertEqual(
            "ok",
            stage.execute_chapter_structure(
                self.database_url, job_id=job_id, worker=WORKER,
                plan=plan, text=text, lease_seconds=300,
            ),
        )
        self.assertEqual(
            "ok",
            stage.execute_chapter_segment(
                self.database_url, job_id=job_id, worker=WORKER,
                plan=plan, requests=requests, lease_seconds=300,
            ),
        )
        self.assertEqual(
            "ok",
            stage.execute_chapter_extract(
                self.database_url, job_id=job_id, worker=WORKER,
                plan=plan, requests=requests, model=model,
                limits=chapter_contract.ChapterLimits(), lease_seconds=300,
            ),
        )
        stage.execute_chapter_assemble(
            self.database_url, job_id=job_id, worker=WORKER,
            plan=plan, lease_seconds=300,
        )
        self.assertEqual(
            "ok",
            stage.execute_chapter_resolve(
                self.database_url, job_id=job_id, worker=WORKER,
                plan=plan, lease_seconds=300,
            ),
        )
        return job_id, revision_id, source_sha, plan, model

    def _publish(self, job_id, plan):
        with psycopg.connect(self.database_url) as conn:
            result = R.publish_chapters(
                conn, job_id=job_id, worker=WORKER, chapter_plan=plan
            )
            conn.commit()
        return result

    # -- end-to-end reading publication ---------------------------------

    def test_full_pipeline_publishes_chapters_and_reading_stream(self) -> None:
        text = TEXT_DISTINCT
        job_id, revision_id, source_sha = self._queue_job(text)
        model, plan = self._prepare_model(
            text, revision_id, source_sha
        )

        claimed, outcome = self._run_once(job_id, text, source_sha, model)

        self.assertEqual(job_id, claimed)
        self.assertEqual("completed", outcome)
        self.assertGreaterEqual(model.calls, 2)

        with psycopg.connect(self.database_url) as conn:
            accepted = chapter_store.read_accepted_chapters(conn, job_id=job_id)
            self.assertEqual(2, len(accepted))
            for entry in accepted:
                self.assertEqual("0.2", entry["artifact"]["version"])
                self.assertTrue(entry["artifact"].get("reading_units"))
            published = chapter_store.list_published_chapters(
                conn, job_id=job_id, limit=100
            )
            self.assertEqual(2, len(published))
            catalog = R.read_latest_catalog(conn)
            self.assertIsNotNone(catalog)
            catalog_sha = R.sha256_json(catalog)

        row = self._reading_stream_row(revision_id)
        self.assertIsNotNone(row, "0.2 publish must expose one reading stream")
        stream_id = str(row[0])
        self.assertEqual(2, int(row[2]))
        self.assertEqual(1, int(row[3]))
        self.assertEqual(
            {item["publication_id"] for item in published},
            {str(value) for value in row[1]},
        )

        with psycopg.connect(self.database_url) as conn:
            stream = reading_store.read_reading_stream(
                conn, stream_id=uuid.UUID(stream_id)
            )
            self.assertEqual(str(revision_id), stream["revision_id"])
            self.assertEqual(catalog_sha, stream["origin_catalog_sha"])
            page = reading_store.read_reading_units(
                conn, stream_id=uuid.UUID(stream_id), limit=50
            )
            groups = reading_store.read_reading_groups(
                conn, stream_id=uuid.UUID(stream_id), limit=50
            )
            self.assertEqual(2, len(page["items"]))
            self.assertEqual(1, len(groups["items"]))
            group = groups["items"][0]
            self.assertEqual(2, group["unit_count"])
            self.assertEqual(page["items"][0]["unit_id"], group["first_unit_id"])
            self.assertEqual(page["items"][-1]["unit_id"], group["last_unit_id"])

            # Every unit's segments reassemble its published translation block
            # verbatim, so the reading index never copies or rewrites the body.
            publications = {
                item["publication_id"]: chapter_store.read_published_chapter(
                    conn, publication_id=uuid.UUID(item["publication_id"])
                )
                for item in published
            }
            for unit in page["items"]:
                full = publications[unit["publication_id"]]
                blocks = {
                    block["block_id"]: block
                    for block in full["publication"]["translation_blocks"]
                }
                block = blocks[unit["block_id"]]
                self.assertEqual(
                    _sha256(block["text"]), unit["text_hash"]
                )
                self.assertEqual(
                    block["text"],
                    "".join(
                        segment["text"] for segment in unit["segments"]
                    ),
                )

        # Occurrences are reverse-indexed for the current narrative events.
        with psycopg.connect(self.database_url) as conn:
            occurrences = conn.execute(
                """
                SELECT count(*) FROM chronicle.reading_event_occurrences
                WHERE stream_id = %s AND event_kind = 'current'
                """,
                (uuid.UUID(stream_id),),
            ).fetchone()[0]
        self.assertGreaterEqual(int(occurrences), 1)

        # present verified the stream binds exactly these publications.
        with psycopg.connect(self.database_url) as conn:
            checkpoint = conn.execute(
                """
                SELECT checkpoint FROM chronicle.ingestion_job_stages
                WHERE job_id = %s AND stage = 'present'
                """,
                (job_id,),
            ).fetchone()[0]
        self.assertEqual(stream_id, checkpoint["reading_stream_id"])

    # -- replay reuse ---------------------------------------------------

    def test_recompile_replays_same_stream_and_units(self) -> None:
        text = TEXT_DISTINCT
        job_id, revision_id, source_sha = self._queue_job(text)
        model, plan = self._prepare_model(text, revision_id, source_sha)
        self.assertEqual("completed", self._run_once(job_id, text, source_sha, model)[1])

        row = self._reading_stream_row(revision_id)
        self.assertIsNotNone(row)
        stream_id = row[0]
        with psycopg.connect(self.database_url) as conn:
            original_units = [
                item["unit_id"]
                for item in reading_store.read_reading_units(
                    conn, stream_id=stream_id, limit=50
                )["items"]
            ]
            accepted = chapter_store.read_accepted_chapters(conn, job_id=job_id)
            published = chapter_store.list_published_chapters(
                conn, job_id=job_id, limit=100
            )
            catalog = R.read_latest_catalog(conn)
            document_id = conn.execute(
                "SELECT document_id FROM chronicle.document_revisions"
                " WHERE revision_id = %s",
                (revision_id,),
            ).fetchone()[0]

        rebuilt_plan = _plan_for(text, revision_id, source_sha)
        publication_by_chapter = {
            item["chapter_id"]: item["publication_id"] for item in published
        }
        bundle_label = R.new_bundle_label(revision_id)
        seed = R.reading_stream_seed(revision_id)
        projection = RP.compile_reading_projection(
            accepted_artifacts=[entry["artifact"] for entry in accepted],
            chapter_plan=rebuilt_plan,
            catalog=catalog,
            stream_id=seed,
            publication_by_chapter=publication_by_chapter,
            bundle_label=bundle_label,
        )
        payload = R.build_reading_stream_payload(
            projection=projection,
            catalog=catalog,
            revision_id=revision_id,
            document_id=document_id,
            chapter_publication_ids=R._ordered_chapter_publications(
                projection, publication_by_chapter
            ),
            artifact_sha256_by_chapter={
                entry["chapter_id"]: entry["artifact_sha256"]
                for entry in accepted
            },
            bundle_label=bundle_label,
        )
        # Rebuilding the compiled bytes twice is byte-identical.
        self.assertEqual(
            RP.projection_canonical_bytes(projection),
            RP.projection_canonical_bytes(
                RP.compile_reading_projection(
                    accepted_artifacts=[entry["artifact"] for entry in accepted],
                    chapter_plan=rebuilt_plan,
                    catalog=catalog,
                    stream_id=seed,
                    publication_by_chapter=publication_by_chapter,
                    bundle_label=bundle_label,
                )
            ),
        )
        with psycopg.connect(self.database_url) as conn:
            replay_id = reading_store.persist_reading_stream(conn, payload)
            conn.commit()
            self.assertEqual(stream_id, replay_id)
            self.assertEqual(
                original_units,
                [
                    item["unit_id"]
                    for item in reading_store.read_reading_units(
                        conn, stream_id=stream_id, limit=50
                    )["items"]
                ],
            )
            self.assertEqual(
                2,
                conn.execute(
                    "SELECT count(*) FROM chronicle.reading_units WHERE stream_id = %s",
                    (stream_id,),
                ).fetchone()[0],
            )

    # -- atomicity under injected faults --------------------------------

    def test_publish_faults_leave_no_partial_public_content(self) -> None:
        text = TEXT_DISTINCT
        job_id, revision_id, _source_sha, plan, model = self._run_to_publish(text)
        calls_after_extract = model.calls
        self.assertGreaterEqual(calls_after_extract, 2)
        self.assertIsNone(self._reading_stream_row(revision_id))

        real_persist_catalog = canonical_store.persist_catalog
        real_insert_publication = chapter_store.insert_chapter_publication_in_txn
        real_persist_stream = reading_store.persist_reading_stream
        real_write_checkpoint = control_plane.write_stage_checkpoint_fenced

        def catalog_then_fail(conn, catalog):
            real_persist_catalog(conn, catalog)
            raise RuntimeError("injected fault after catalog")

        def chapters_then_fail(*args, **kwargs):
            real_insert_publication(*args, **kwargs)
            raise RuntimeError("injected fault after chapters")

        def stream_then_fail(*args, **kwargs):
            real_persist_stream(*args, **kwargs)
            raise RuntimeError("injected fault during reading index")

        def checkpoint_then_fail(*args, **kwargs):
            real_write_checkpoint(*args, **kwargs)
            raise RuntimeError("injected fault before publish checkpoint")

        faults = (
            ("canonical_store", "persist_catalog", catalog_then_fail),
            (
                "chapter_store",
                "insert_chapter_publication_in_txn",
                chapters_then_fail,
            ),
            ("reading_store", "persist_reading_stream", stream_then_fail),
            (
                "control_plane",
                "write_stage_checkpoint_fenced",
                checkpoint_then_fail,
            ),
        )
        import importlib

        for module_name, attr, replacement in faults:
            module = importlib.import_module(module_name)
            with mock.patch.object(module, attr, replacement):
                with psycopg.connect(self.database_url) as conn:
                    with self.assertRaises(RuntimeError):
                        R.publish_chapters(
                            conn, job_id=job_id, worker=WORKER,
                            chapter_plan=plan,
                        )
                    conn.rollback()
            counts = self._public_counts()
            for table, count in counts.items():
                self.assertEqual(
                    0, count,
                    f"{table} leaked public rows after {module_name}.{attr} fault",
                )

        # A clean retry after every fault publishes the whole index.
        result = self._publish(job_id, plan)
        self.assertIn("reading_stream_id", result)
        self.assertEqual(2, result["reading_unit_count"])
        counts = self._public_counts()
        self.assertEqual(1, counts["canonical_catalogs"])
        self.assertEqual(2, counts["chapter_publications"])
        self.assertEqual(1, counts["reading_streams"])
        self.assertEqual(2, counts["reading_units"])
        self.assertGreaterEqual(counts["reading_time_groups"], 1)
        # Publishing (and every failed attempt above) never calls the model:
        # the reading index is compiled from the accepted artifacts only.
        self.assertEqual(calls_after_extract, model.calls)

    # -- drift rejection ------------------------------------------------

    def test_drifted_chapter_plan_is_rejected_without_public_content(self) -> None:
        text = TEXT_DISTINCT
        job_id, revision_id, _source_sha, plan, _model = self._run_to_publish(text)
        drifted = json.loads(json.dumps(plan))
        drifted["chapters"][0]["content_sha256"] = "0" * 64

        with psycopg.connect(self.database_url) as conn:
            with self.assertRaises(PersistenceError):
                R.publish_chapters(
                    conn, job_id=job_id, worker=WORKER, chapter_plan=drifted
                )
            conn.rollback()

        counts = self._public_counts()
        for table, count in counts.items():
            self.assertEqual(0, count, f"{table} leaked after plan drift")
        self.assertIsNone(self._reading_stream_row(revision_id))

        # A 0.2 accepted job without a chapter plan cannot publish a reading
        # index either: it fails closed rather than publishing chapters alone.
        with psycopg.connect(self.database_url) as conn:
            with self.assertRaises(PersistenceError):
                R.publish_chapters(conn, job_id=job_id, worker=WORKER)
            conn.rollback()
        self.assertEqual(0, self._public_counts()["canonical_catalogs"])


if __name__ == "__main__":
    unittest.main()
