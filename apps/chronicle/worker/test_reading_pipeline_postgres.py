"""PostgreSQL 18 integration tests for the current 0.4 reading publication wiring.

Proves the production chapter chain publishes the canonical catalog, every
complete chapter and the whole immutable reading index in one transaction:

- a fresh 0.4 revision flows through extract/assemble/resolve/publish/present
  and exposes exactly one reading stream whose units reassemble the published
  translation blocks and whose groups/occurrences are readable by the T05
  helpers;
- recompiling and replaying the same revision reuses the identical stream and
  unit IDs without any additional model call;
- a fault injected after the catalog, after the chapters, while writing the
  reading index and before the publish checkpoint leaves zero public content
  (no catalog, no chapter publication, no reading stream/unit/group/
  occurrence), and a clean retry then succeeds;
- a chapter plan whose content hashes drift from the accepted 0.4 artifacts is
  rejected fail-closed with no public rows.

The current staged model is the explicit in-process fixture injection; model
transport selection is covered by the staged provider tests. The stream/event
read APIs belong to T07/T08 and are not fabricated here.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
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
from common import LeaseLost, PersistenceError  # noqa: E402
from migrations import apply_migrations  # noqa: E402

import chapter_stage as stage  # noqa: E402
import ingestion_worker as worker  # noqa: E402
import person_state_review  # noqa: E402
import reading_projection as RP  # noqa: E402
import reading_store  # noqa: E402
import resolve_publish as R  # noqa: E402
from staged_pipeline_fixture import ScriptedModels  # noqa: E402


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


class CurrentStagedModel:
    """Current staged fixture plus a scalar call counter for assertions."""

    def __init__(self) -> None:
        self.script = ScriptedModels()
        self.models = self.script.models

    @property
    def calls(self) -> int:
        return sum(self.script.calls.values())


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
        return CurrentStagedModel(), plan

    def _run_once(self, job_id, text, source_sha, model, **kwargs):
        result = worker.run_once(
            self.database_url, worker=WORKER,
            revision_source=lambda _job: (text, source_sha),
            chapter_model=model.models,
            chapter_limits=chapter_contract.ChapterLimits(),
            job_id=job_id, **kwargs,
        )
        if result[1] == "needs_review" and self.__class__ is ReadingPipelinePostgresTests:
            self._approve_person_state(job_id)
            result = worker.run_once(
                self.database_url, worker=WORKER,
                revision_source=lambda _job: (text, source_sha),
                chapter_model=model.models,
                chapter_limits=chapter_contract.ChapterLimits(),
                job_id=job_id, **kwargs,
            )
        return result

    def _approve_person_state(self, job_id):
        with psycopg.connect(self.database_url) as conn:
            stored = R.read_person_state_plan_output(conn, job_id=job_id)
        if not isinstance(stored, dict) or not isinstance(stored.get("plan"), dict):
            raise AssertionError("current 0.4 run did not persist a person-state plan")
        plan = stored["plan"]
        with psycopg.connect(self.database_url) as conn:
            rows = conn.execute(
                "SELECT review_id, payload FROM chronicle.review_items"
                " WHERE job_id = %s AND payload->>'scope' = 'person_state'"
                " ORDER BY created_at, review_id",
                (job_id,),
            ).fetchall()
            for review_id, payload in rows:
                package = next(
                    item for item in plan["packages"]
                    if item["chapter_id"] == payload["chapter_id"]
                )
                person_state_review.resolve_person_state_review(
                    conn,
                    job_id=job_id,
                    review_id=review_id,
                    plan=plan,
                    decision={
                        "default_assessment": "supported",
                        "rationale": "测试夹具中的当前阶段证据已核对。",
                        "overrides": [
                            {
                                "candidate_id": candidate["candidate_key"],
                                "assessment": "supported",
                                "rationale": "测试夹具中的原文锚点支持。",
                            }
                            for candidate in package["candidates"]
                        ],
                    },
                )
            conn.commit()
            control_plane.resume_job(conn, job_id=job_id)
            conn.commit()

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
        """Drive the chapter chain to a running publish stage (0.4 artifacts)."""
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
            candidate_version="0.4",
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
                plan=plan, requests=requests, model=model.models,
                limits=chapter_contract.ChapterLimits(), lease_seconds=300,
            ),
        )
        stage.execute_chapter_assemble(
            self.database_url, job_id=job_id, worker=WORKER,
            plan=plan, lease_seconds=300,
        )
        outcome = stage.execute_chapter_resolve(
            self.database_url, job_id=job_id, worker=WORKER,
            plan=plan, lease_seconds=300,
        )
        if outcome == "needs_review":
            with psycopg.connect(self.database_url) as conn:
                control_plane.advance_stage(
                    conn, job_id=job_id, stage="resolve", status="needs_review",
                    error="current person-state review pending",
                )
                control_plane.set_job_status(
                    conn, job_id=job_id, status="needs_review",
                    error="current person-state review pending",
                )
            self._approve_person_state(job_id)
            with psycopg.connect(self.database_url) as conn:
                control_plane.claim_job(
                    conn, worker=WORKER, lease_seconds=300, job_id=job_id
                )
                conn.commit()
            outcome = stage.execute_chapter_resolve(
                self.database_url, job_id=job_id, worker=WORKER,
                plan=plan, lease_seconds=300,
            )
        self.assertEqual("ok", outcome)
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
                self.assertEqual("0.4", entry["artifact"]["version"])
                self.assertTrue(entry["artifact"].get("reading_units"))
            published = chapter_store.list_published_chapters(
                conn, job_id=job_id, limit=100
            )
            self.assertEqual(2, len(published))
            catalog = R.read_latest_catalog(conn)
            self.assertIsNotNone(catalog)
            catalog_sha = R.sha256_json(catalog)

        row = self._reading_stream_row(revision_id)
        self.assertIsNotNone(row, "0.4 publish must expose one reading stream")
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

        # Occurrences are reverse-indexed for the current narrative events or
        # their resolved translated spans.
        with psycopg.connect(self.database_url) as conn:
            occurrences = conn.execute(
                """
                SELECT count(*) FROM chronicle.reading_event_occurrences
                WHERE stream_id = %s AND event_kind IN ('current', 'span')
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

        # A current accepted job without a chapter plan cannot publish a reading
        # index either: it fails closed rather than publishing chapters alone.
        with psycopg.connect(self.database_url) as conn:
            with self.assertRaises(PersistenceError):
                R.publish_chapters(conn, job_id=job_id, worker=WORKER)
            conn.rollback()
        self.assertEqual(0, self._public_counts()["canonical_catalogs"])

    def test_plan_binding_drift_is_rejected_without_public_content(self) -> None:
        """Top-level plan drift must not reach the reading manifest.

        Reproduces the reviewer's case: rewriting the plan's
        ``normalized_sha256`` (which assembly never validated) previously
        published a reading stream with the wrong hash. The plan is now bound
        to the persisted T03/assembled record, so every drift fails closed.
        """
        text = TEXT_DISTINCT
        job_id, revision_id, _source_sha, plan, _model = self._run_to_publish(text)

        def _drifting_plan(mutate):
            drifted = json.loads(json.dumps(plan))
            mutate(drifted)
            return drifted

        cases = (
            ("normalized_sha256", lambda p: p.update({"normalized_sha256": "f" * 64})),
            ("source_sha256", lambda p: p.update({"source_sha256": "e" * 64})),
            ("revision_id", lambda p: p.update({"revision_id": str(uuid.uuid4())})),
            ("plan_sha256", lambda p: p.update({"plan_sha256": "0" * 64})),
            (
                "chapter geometry",
                lambda p: p["chapters"][0].update(
                    {"start": int(p["chapters"][0]["start"]) + 1}
                ),
            ),
            # In-chapter covered fields: the canonical plan hash covers every
            # chapter block, so tampering them while keeping the original
            # plan_sha256 must still be rejected.
            (
                "chapter block content_sha256",
                lambda p: p["chapters"][0]["blocks"][0].update(
                    {"content_sha256": "0" * 64}
                ),
            ),
            (
                "chapter block range",
                lambda p: p["chapters"][0]["blocks"][0].update(
                    {"start": int(p["chapters"][0]["blocks"][0]["start"]) + 1}
                ),
            ),
            (
                "required_block_ids",
                lambda p: p["chapters"][0].update({"required_block_ids": []}),
            ),
            (
                "re-hashed block drift",
                lambda p: (
                    p["chapters"][0]["blocks"][0].update(
                        {"content_sha256": "1" * 64}
                    ),
                    p.update({"plan_sha256": chapter_plan.plan_sha256_for(p)}),
                ),
            ),
        )
        for label, mutate in cases:
            drifted = _drifting_plan(mutate)
            with psycopg.connect(self.database_url) as conn:
                with self.assertRaises(PersistenceError, msg=label):
                    R.publish_chapters(
                        conn, job_id=job_id, worker=WORKER, chapter_plan=drifted
                    )
                conn.rollback()
            counts = self._public_counts()
            for table, count in counts.items():
                self.assertEqual(
                    0, count, f"{table} leaked after {label} drift"
                )
            self.assertIsNone(self._reading_stream_row(revision_id))

        # The genuine plan still publishes (the rejected attempts wrote nothing).
        result = self._publish(job_id, plan)
        self.assertIn("reading_stream_id", result)
        self.assertEqual(1, self._public_counts()["reading_streams"])

    # -- lease expiry during the publish transaction ---------------------

    def _shorten_lease(self, job_id, seconds: int) -> None:
        with psycopg.connect(self.database_url) as conn:
            conn.execute(
                "UPDATE chronicle.ingestion_jobs "
                "SET lease_expires_at = clock_timestamp() + make_interval(secs => %s) "
                "WHERE job_id = %s",
                (seconds, job_id),
            )
            conn.commit()

    def _assert_no_public_content(self, revision_id) -> None:
        for table, count in self._public_counts().items():
            self.assertEqual(0, count, f"{table} leaked public rows")
        self.assertIsNone(self._reading_stream_row(revision_id))

    def test_lease_expiry_during_assemble_fails_before_first_public_write(self) -> None:
        """A lease that expires while assemble runs cannot commit.

        The lease is only 2 s while the injected assemble sleeps 3 s, so the
        live-clock fence between the expensive computation and the first
        public write must fail closed and roll back every row.
        """
        text = TEXT_DISTINCT
        job_id, revision_id, _source_sha, plan, _model = self._run_to_publish(text)
        self._shorten_lease(job_id, 2)

        original = R.chapter_assembly.assemble_chapters

        def slow_assemble(*args, **kwargs):
            time.sleep(3.0)
            return original(*args, **kwargs)

        with mock.patch.object(
            R.chapter_assembly, "assemble_chapters", slow_assemble
        ):
            with psycopg.connect(self.database_url) as conn:
                with self.assertRaises(LeaseLost):
                    R.publish_chapters(
                        conn, job_id=job_id, worker=WORKER, chapter_plan=plan
                    )
                conn.rollback()
        self._assert_no_public_content(revision_id)

        # Renewing the lease and retrying publishes normally (fence, not data).
        with psycopg.connect(self.database_url) as conn:
            conn.execute(
                "UPDATE chronicle.ingestion_jobs SET lease_expires_at = "
                "clock_timestamp() + interval '300 seconds' WHERE job_id = %s",
                (job_id,),
            )
            conn.commit()
        self.assertIn("reading_stream_id", self._publish(job_id, plan))

    def test_lease_expiry_during_reading_compile_fails_before_stream_write(self) -> None:
        """A lease that expires inside the reading compile cannot commit.

        Catalog and chapter publications are already written in the
        transaction when the compile runs; the live-clock fence after the
        compile must raise ``LeaseLost`` and roll all of them back instead of
        committing a catalog + chapters with no/partial reading index.
        """
        text = TEXT_DISTINCT
        job_id, revision_id, _source_sha, plan, _model = self._run_to_publish(text)
        self._shorten_lease(job_id, 2)

        original = R.reading_projection.compile_reading_projection

        def slow_compile(*args, **kwargs):
            time.sleep(3.0)
            return original(*args, **kwargs)

        with mock.patch.object(
            R.reading_projection, "compile_reading_projection", slow_compile
        ):
            with psycopg.connect(self.database_url) as conn:
                with self.assertRaises(LeaseLost):
                    R.publish_chapters(
                        conn, job_id=job_id, worker=WORKER, chapter_plan=plan
                    )
                conn.rollback()
        self._assert_no_public_content(revision_id)


if __name__ == "__main__":
    unittest.main()
