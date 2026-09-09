"""PostgreSQL 18 integration tests for the C2-R1-T13 chapter pipeline.

Proves the sole worker wiring end to end against a real database: a new
revision flows through chapter extract, assembly, human review, and the
atomic publish; kill/takeover, slow-model adoption, cancellation, expired
leases, and accepted-run recovery never double-accept or drop artifacts;
any missing/invalid chapter, open review, or wrong frozen plan blocks all
public content; waiting publishers resolve latest-catalog order by
``publication_sequence`` (never ``imported_at``); a moved baseline fails
closed as ``publication_plan_stale``; publications bind the original
artifact/revision; same-revision content changes are rejected; and
``present`` verifies published artifacts without re-translating.

The joint chapter model is the explicit fixture-pack test injection
(``FixtureChapterModel``); production model selection is covered by
``test_production_worker_budget_unit.py``.
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

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
for path in (str(HERE), str(PERSISTENCE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import control_plane  # noqa: E402
import chapter_contract  # noqa: E402
import chapter_plan  # noqa: E402
import chapter_prompt  # noqa: E402
import chapter_store  # noqa: E402
from common import PersistenceConflict, PersistenceError  # noqa: E402
from common import LeaseLost  # noqa: E402
from migrations import apply_migrations  # noqa: E402

import assembly as chapter_assembly  # noqa: E402
import chapter_stage as stage  # noqa: E402
import ingestion_worker as worker  # noqa: E402
import resolve_publish  # noqa: E402


DEFAULT_CONTROL_URL = "postgresql://loom:loom@127.0.0.1:15432/loom_control"


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


TEXT_DISTINCT = """# 測試書

## 先主傳

劉備字玄德，涿郡涿縣人也。漢景帝子中山靖王勝之後也。備少孤，與母以織席販履為業。

## 周瑜傳

周瑜字公瑾，廬江舒人也。瑜長壯有姿貌，精音律，江東諺云曲有誤周郎顧。
"""

TEXT_SHARED_NAME = """# 測試書

## 先主傳上

劉備屯新野，聞徐庶之名而往見之。庶曰將軍欲成霸業，宜尋訪賢士。

## 先主傳下

劉備三顧茅廬於隆中，孔明乃許備以驅馳。時曹公南征，備走江陵。
"""


def _plan_for(text: str, revision_id: uuid.UUID, source_sha: str):
    locator = {
        "revision_id": str(revision_id),
        "source_sha256": source_sha,
        "normalized_sha256": _sha256(text),
    }
    return chapter_plan.plan_chapters(
        text, locator, "liezhuan.md",
        limits=chapter_contract.ChapterLimits(),
    )


def _pack_payload(plan, revision_id: uuid.UUID, specs: list[dict]) -> dict:
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
        "model_version": "t13-test",
        "chapters": chapters,
    }


def _load_fixture_model(pack: dict):
    import fixture_model as fixture_model  # noqa: E402

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as handle:
        json.dump(pack, handle, ensure_ascii=False)
        path = handle.name
    try:
        return fixture_model.models_from_chapter_fixture_pack(path)
    finally:
        os.unlink(path)


def _distinct_specs() -> list[dict]:
    return [
        {
            "translation": "劉備，字玄德，乃漢室宗親，以織席販履為業。",
            "entities": [
                {"name": "劉備", "type": "person", "mention": "劉備"},
            ],
            "event": {"type": "other", "title": "劉備織席販履"},
        },
        {
            "translation": "周瑜，字公瑾，姿貌雄偉，精通音律。",
            "entities": [
                {"name": "周瑜", "type": "person", "mention": "周瑜"},
            ],
            "event": {"type": "cultural", "title": "周瑜顧曲"},
        },
    ]


def _shared_specs() -> list[dict]:
    return [
        {
            "translation": "劉備屯兵新野，往見徐庶以求霸業之策。",
            "entities": [
                {"name": "劉備", "type": "person", "mention": "劉備"},
            ],
            "event": {"type": "movement", "title": "劉備見徐庶"},
        },
        {
            "translation": "劉備三顧茅廬，孔明許以驅馳，共圖大業。",
            "entities": [
                {"name": "劉備", "type": "person", "mention": "劉備"},
            ],
            "event": {"type": "movement", "title": "劉備三顧茅廬"},
        },
    ]


def _parse_chapter_request_header(prompt: str) -> dict:
    """Parse the exact T05 ``CHAPTER REQUEST`` header envelope.

    The production prompt carries the program-owned request header as
    one JSON object on the lines between ``CHAPTER REQUEST`` and the
    next blank line. This parses that exact envelope (no chapter-id
    guessing): the T06 fixture still needs a ``CHAPTER_REQUEST``
    envelope it does not emit, which is flagged for the T06 owner —
    the adapter below only bridges it inside this test.
    """
    if not isinstance(prompt, str) or not prompt:
        raise PersistenceError("chapter prompt must be non-empty text")
    marker = "CHAPTER REQUEST\n"
    start = prompt.find(marker)
    if start < 0:
        raise PersistenceError(
            "chapter prompt carries no CHAPTER REQUEST envelope"
        )
    rest = prompt[start + len(marker):]
    lines: list[str] = []
    for line in rest.splitlines():
        if not line.strip():
            break
        lines.append(line)
    try:
        header = json.loads("\n".join(lines))
    except json.JSONDecodeError as exc:
        raise PersistenceError(
            "CHAPTER REQUEST header is not parseable JSON"
        ) from exc
    if not isinstance(header, dict):
        raise PersistenceError("CHAPTER REQUEST header must be an object")
    for key in (
        "chapter_id", "revision_id", "source_sha256",
        "normalized_sha256", "limits", "prompt_version",
    ):
        if header.get(key) in (None, ""):
            raise PersistenceError(
                f"CHAPTER REQUEST header is missing {key!r}"
            )
    return header


class ExplodingModel:
    """Joint model that fails if ever called (adoption must need no calls)."""

    name = "exploding-test-model"
    calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        raise AssertionError("model must not be called during adoption")


class ChapterContractRegressionTests(unittest.TestCase):
    """Pure regression tests for the wired T01/T03/T05/T07 contracts."""

    def test_chapter_request_header_envelope_is_exact(self) -> None:
        text = TEXT_DISTINCT
        revision_id = uuid.uuid4()
        plan = _plan_for(text, revision_id, _sha256(text))
        request = chapter_plan.build_chapter_request(
            plan, 0, text, limits=chapter_contract.ChapterLimits()
        )
        prompt = chapter_prompt.render_chapter_prompt(request)
        header = _parse_chapter_request_header(prompt)
        self.assertEqual(request["chapter_id"], header["chapter_id"])
        self.assertEqual(request["revision_id"], header["revision_id"])
        self.assertEqual(request["source_sha256"], header["source_sha256"])
        self.assertEqual(request["limits"], header["limits"])

    def test_real_fixture_answers_t05_prompt_directly(self) -> None:
        text = TEXT_DISTINCT
        revision_id = uuid.uuid4()
        plan = _plan_for(text, revision_id, _sha256(text))
        pack = _pack_payload(plan, revision_id, _distinct_specs())
        fixture = _load_fixture_model(pack)
        request = chapter_plan.build_chapter_request(
            plan, 1, text, limits=chapter_contract.ChapterLimits()
        )
        request["normalized_sha256"] = _sha256(request["normalized_text"])
        prompt = chapter_prompt.render_chapter_prompt(request)
        candidate = json.loads(fixture.complete(prompt))
        self.assertEqual(request["chapter_id"], candidate["chapter_id"])
        report = chapter_contract.validate_chapter_candidate(request, candidate)
        self.assertTrue(report["passed"])

    def test_assembly_requires_per_chapter_content_hash(self) -> None:
        fixtures = HERE.parent / "ingestion" / "fixtures" / "c2r1-contract"
        request = json.loads((fixtures / "request.json").read_text(encoding="utf-8"))
        candidate = json.loads(
            (fixtures / "candidate-valid.json").read_text(encoding="utf-8")
        )
        artifact = chapter_contract.accept_chapter_candidate(
            request, candidate,
            producing_run={
                "run_id": "run-regression",
                "model": "m",
                "prompt_schema_version": "v",
            },
        )
        base_chapter = {
            "chapter_id": request["chapter_id"],
            "chapter_index": 0,
            "title": "e2e",
            "start": 0,
            "end": len(request["normalized_text"]),
        }
        base_plan = {
            "version": "c2r1-chapters-v1",
            "plan_sha256": "e" * 64,
            "revision_id": request["revision_id"],
            "source_sha256": request["source_sha256"],
            "normalized_sha256": request["normalized_sha256"],
        }
        # A plan without the per-chapter content hash is rejected even
        # for a real accepted artifact.
        missing = dict(base_plan, chapters=[dict(base_chapter)])
        with self.assertRaises(PersistenceError):
            chapter_assembly.assemble_chapters(
                accepted_artifacts=[artifact], chapter_plan=missing
            )
        # A wrong content hash is rejected just as loudly.
        wrong = dict(
            base_plan,
            chapters=[dict(base_chapter, content_sha256="0" * 64)],
        )
        with self.assertRaises(PersistenceError):
            chapter_assembly.assemble_chapters(
                accepted_artifacts=[artifact], chapter_plan=wrong
            )
        # The matching content hash assembles (single-chapter fixture:
        # the request hash already binds the whole slice).
        good = dict(
            base_plan,
            chapters=[
                dict(base_chapter, content_sha256=request["normalized_sha256"])
            ],
        )
        result = chapter_assembly.assemble_chapters(
            accepted_artifacts=[artifact], chapter_plan=good
        )
        self.assertIn("bundle", result)


class ChapterPipelinePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_t13_test_{uuid.uuid4().hex}"
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
            conn.commit()

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

    def _run_once(self, job_id, text, source_sha, model, **kwargs):
        return worker.run_once(
            self.database_url, worker="worker-t13",
            revision_source=lambda _job: (text, source_sha),
            chapter_model=model,
            chapter_limits=chapter_contract.ChapterLimits(),
            job_id=job_id, **kwargs,
        )

    def _prepare_model(self, text, revision_id, source_sha, specs):
        # The real T06 fixture path: the pack only binds chapter_ids;
        # every prompt is a production T05 render parsed by the fixture
        # itself, with no test-only adapter in between.
        plan = _plan_for(text, revision_id, source_sha)
        pack = _pack_payload(plan, revision_id, specs)
        return _load_fixture_model(pack), plan

    def _planned_requests(self, text, job_id, source_sha):
        """Build production-identical requests via the T13 wiring layer."""
        with psycopg.connect(self.database_url) as conn:
            binding = stage.read_revision_binding(conn, job_id=job_id)
        assert binding["source_sha256"] == source_sha
        _, _, plan, requests = stage.load_chapter_inputs(
            self.database_url, job_id=job_id,
            revision_source=lambda _job: (text, source_sha),
            limits=chapter_contract.ChapterLimits(),
        )
        return plan, requests

    def _open_reviews(self, job_id):
        with psycopg.connect(self.database_url) as conn:
            return conn.execute(
                """
                SELECT review_id, payload FROM chronicle.review_items
                WHERE job_id = %s AND status = 'open'
                ORDER BY review_id
                """,
                (job_id,),
            ).fetchall()

    def _decide_all(self, job_id, decision: str) -> None:
        for review_id, payload in self._open_reviews(job_id):
            link_kind = payload.get("link_kind")
            if link_kind == "entity":
                terminal = decision
            else:
                terminal = (
                    "related_occurrence"
                    if decision == "not_same"
                    else "same_occurrence"
                )
            with psycopg.connect(self.database_url) as conn:
                resolve_publish.resolve_resolution_review(
                    conn, review_id=review_id, decision=terminal,
                    rationale=f"t13 test decision {terminal}",
                )
                conn.commit()

    def _job_status(self, job_id) -> tuple[str, str | None]:
        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                "SELECT status, error FROM chronicle.ingestion_jobs WHERE job_id = %s",
                (job_id,),
            ).fetchone()
        return row[0], row[1]

    def _advance_running(self, job_id, *stages) -> None:
        with psycopg.connect(self.database_url) as conn:
            for stage_name in stages:
                control_plane.advance_stage(
                    conn, job_id=job_id, stage=stage_name, status="running"
                )
            conn.commit()

    # -- full pipeline: unattended publish --------------------------------

    def test_full_pipeline_extract_assemble_publish_present(self) -> None:
        text = TEXT_DISTINCT
        job_id, revision_id, source_sha = self._queue_job(text)
        model, plan = self._prepare_model(
            text, revision_id, source_sha, _distinct_specs()
        )

        claimed, outcome = self._run_once(job_id, text, source_sha, model)

        self.assertEqual(job_id, claimed)
        self.assertEqual("completed", outcome)
        with psycopg.connect(self.database_url) as conn:
            accepted = chapter_store.read_accepted_chapters(conn, job_id=job_id)
            self.assertEqual(2, len(accepted))
            published = chapter_store.list_published_chapters(
                conn, job_id=job_id, limit=100
            )
            self.assertEqual(2, len(published))
            catalog_rows = conn.execute(
                "SELECT artifact_sha256, publication_sequence "
                "FROM chronicle.canonical_catalogs"
            ).fetchall()
            self.assertEqual(1, len(catalog_rows))
            for item in published:
                full = chapter_store.read_published_chapter(
                    conn, publication_id=uuid.UUID(item["publication_id"])
                )
                blocks = full["publication"]["translation_blocks"]
                self.assertGreater(len(blocks), 0)
                for block in blocks:
                    self.assertTrue(block["text"].strip())
                self.assertEqual(
                    catalog_rows[0][0], full["publication"]["catalog_sha256"]
                )
                self.assertEqual(
                    item["artifact_sha256"], full["artifact_sha256"]
                )
            # Catalog and readable translations went public together.
            outputs = conn.execute(
                """
                SELECT artifact_type FROM chronicle.ingestion_outputs
                WHERE job_id = %s
                """,
                (job_id,),
            ).fetchall()
            types = {row[0] for row in outputs}
            self.assertIn("assembled-source-bundle", types)
            self.assertIn("chapter-review-plan", types)
            self.assertIn("canonical-catalog", types)

    def test_review_gated_resume_then_publish(self) -> None:
        text = TEXT_SHARED_NAME
        job_id, revision_id, source_sha = self._queue_job(text)
        model, _ = self._prepare_model(
            text, revision_id, source_sha, _shared_specs()
        )

        _, outcome = self._run_once(job_id, text, source_sha, model)
        self.assertEqual("needs_review", outcome)
        reviews = self._open_reviews(job_id)
        self.assertGreater(len(reviews), 0)

        # No candidate may publish directly: the atomic publish refuses
        # open reviews and writes no public content.
        with psycopg.connect(self.database_url) as conn:
            with self.assertRaises(PersistenceError):
                resolve_publish.publish_chapters(
                    conn, job_id=job_id, worker="worker-t13"
                )
            conn.rollback()
            self.assertEqual(
                0,
                conn.execute(
                    "SELECT count(*) FROM chronicle.chapter_publications"
                ).fetchone()[0],
            )
            self.assertEqual(
                0,
                conn.execute(
                    "SELECT count(*) FROM chronicle.canonical_catalogs"
                ).fetchone()[0],
            )

        self._decide_all(job_id, "not_same")
        with psycopg.connect(self.database_url) as conn:
            control_plane.resume_job(conn, job_id=job_id)
            conn.commit()
        _, outcome = self._run_once(job_id, text, source_sha, model)
        self.assertEqual("completed", outcome)
        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(
                2,
                conn.execute(
                    "SELECT count(*) FROM chronicle.chapter_publications "
                    "WHERE job_id = %s",
                    (job_id,),
                ).fetchone()[0],
            )

    # -- recovery: accepted-run adoption with zero model calls ------------

    def test_accepted_run_adoption_needs_zero_model_calls(self) -> None:
        text = TEXT_DISTINCT
        job_id, revision_id, source_sha = self._queue_job(text)
        model, _ = self._prepare_model(
            text, revision_id, source_sha, _distinct_specs()
        )
        plan, requests = self._planned_requests(text, job_id, source_sha)
        with psycopg.connect(self.database_url) as conn:
            control_plane.claim_job(
                conn, worker="worker-t13", lease_seconds=300, job_id=job_id
            )
            conn.commit()
        # Structure + segment first so chunks exist.
        self._advance_running(job_id, "structure", "segment")
        self.assertEqual(
            "ok",
            stage.execute_chapter_structure(
                self.database_url, job_id=job_id, worker="worker-t13",
                plan=plan, text=text, lease_seconds=300,
            ),
        )
        self.assertEqual(
            "ok",
            stage.execute_chapter_segment(
                self.database_url, job_id=job_id, worker="worker-t13",
                plan=plan, requests=requests, lease_seconds=300,
            ),
        )
        # Simulate the crash window: both accepted runs committed, but
        # neither chunk checkpoint/status commit landed.
        with psycopg.connect(self.database_url) as conn:
            chunks = conn.execute(
                """
                SELECT chunk_id, chunk_index FROM chronicle.ingestion_chunks
                WHERE job_id = %s ORDER BY chunk_index
                """,
                (job_id,),
            ).fetchall()
        for chunk_id, index in chunks:
            request = requests[int(index)]
            from chapter_extraction import extract_chapter as _extract  # noqa: E402

            outcome = _extract(
                request, model,
                limits=chapter_contract.ChapterLimits(),
            )
            self.assertTrue(outcome["accepted"])
            candidate = outcome["artifact"]["candidate"]
            with psycopg.connect(self.database_url) as conn:
                control_plane.record_chunk_run_fenced(
                    conn, job_id=job_id, chunk_id=chunk_id,
                    status="completed", worker="worker-t13",
                    checkpoint={
                        "accepted": True,
                        "request": request,
                        "request_fingerprint": outcome["request_fingerprint"],
                        "candidate": candidate,
                        "attempts": outcome["attempts"],
                        "model": model.name,
                    },
                )
                conn.commit()
        exploding = ExplodingModel()
        outcome = stage.execute_chapter_extract(
            self.database_url, job_id=job_id, worker="worker-t13",
            plan=plan, requests=requests, model=exploding,
            limits=chapter_contract.ChapterLimits(), lease_seconds=300,
        )
        self.assertEqual("ok", outcome)
        self.assertEqual(0, exploding.calls)
        with psycopg.connect(self.database_url) as conn:
            accepted = chapter_store.read_accepted_chapters(conn, job_id=job_id)
            self.assertEqual(2, len(accepted))

    # -- recovery: takeover / cancellation never double-accepts -----------

    def test_takeover_during_extract_writes_nothing(self) -> None:
        text = TEXT_DISTINCT
        job_id, revision_id, source_sha = self._queue_job(text)
        model, _ = self._prepare_model(
            text, revision_id, source_sha, _distinct_specs()
        )
        plan, requests = self._planned_requests(text, job_id, source_sha)
        with psycopg.connect(self.database_url) as conn:
            control_plane.claim_job(
                conn, worker="worker-t13", lease_seconds=300, job_id=job_id
            )
            conn.commit()
        self._advance_running(job_id, "structure", "segment")
        self.assertEqual(
            "ok",
            stage.execute_chapter_structure(
                self.database_url, job_id=job_id, worker="worker-t13",
                plan=plan, text=text, lease_seconds=300,
            ),
        )
        self.assertEqual(
            "ok",
            stage.execute_chapter_segment(
                self.database_url, job_id=job_id, worker="worker-t13",
                plan=plan, requests=requests, lease_seconds=300,
            ),
        )
        # A second worker takes over the lease (simulated claim).
        with psycopg.connect(self.database_url) as conn:
            conn.execute(
                "UPDATE chronicle.ingestion_jobs SET lease_owner = %s "
                "WHERE job_id = %s",
                ("worker-takeover", job_id),
            )
            conn.commit()
        with self.assertRaises(LeaseLost):
            stage.execute_chapter_extract(
                self.database_url, job_id=job_id, worker="worker-t13",
                plan=plan, requests=requests, model=model,
                limits=chapter_contract.ChapterLimits(), lease_seconds=300,
            )
        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(
                0,
                conn.execute(
                    "SELECT count(*) FROM chronicle.ingestion_chunk_runs r "
                    "JOIN chronicle.ingestion_chunks c ON c.chunk_id = r.chunk_id "
                    "WHERE c.job_id = %s",
                    (job_id,),
                ).fetchone()[0],
            )
            self.assertEqual(
                0,
                conn.execute(
                    "SELECT count(*) FROM chronicle.chapter_artifacts WHERE job_id = %s",
                    (job_id,),
                ).fetchone()[0],
            )

    # -- atomicity: stale baseline fails closed ----------------------------

    def test_moved_baseline_publishes_stale_without_public_content(self) -> None:
        # Job B resolves first against the empty baseline.
        text_b = TEXT_SHARED_NAME
        job_b, rev_b, sha_b = self._queue_job(text_b)
        model_b, _ = self._prepare_model(
            text_b, rev_b, sha_b, _shared_specs()
        )
        _, outcome = self._run_once(job_b, text_b, sha_b, model_b)
        self.assertEqual("needs_review", outcome)
        self._decide_all(job_b, "not_same")

        # Job A publishes first and moves the baseline.
        text_a = TEXT_DISTINCT
        job_a, rev_a, sha_a = self._queue_job(text_a)
        model_a, _ = self._prepare_model(
            text_a, rev_a, sha_a, _distinct_specs()
        )
        _, outcome = self._run_once(job_a, text_a, sha_a, model_a)
        self.assertEqual("completed", outcome)

        # Job B resumes against the frozen plan: stale, fail closed.
        with psycopg.connect(self.database_url) as conn:
            control_plane.resume_job(conn, job_id=job_b)
            conn.commit()
        _, outcome = self._run_once(job_b, text_b, sha_b, model_b)
        self.assertEqual("failed", outcome)
        status, error = self._job_status(job_b)
        self.assertEqual("failed", status)
        self.assertIn("publication_plan_stale", error or "")
        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(
                1,
                conn.execute(
                    "SELECT count(*) FROM chronicle.canonical_catalogs"
                ).fetchone()[0],
            )
            self.assertEqual(
                0,
                conn.execute(
                    "SELECT count(*) FROM chronicle.chapter_publications "
                    "WHERE job_id = %s",
                    (job_b,),
                ).fetchone()[0],
            )
            # The frozen plan and its evidence are untouched.
            plan_rows = conn.execute(
                """
                SELECT count(*) FROM chronicle.ingestion_outputs
                WHERE job_id = %s AND artifact_type = %s
                """,
                (job_b, "chapter-review-plan"),
            ).fetchone()[0]
            self.assertEqual(1, plan_rows)

    def test_second_publisher_reads_latest_by_sequence(self) -> None:
        text_a = TEXT_DISTINCT
        job_a, rev_a, sha_a = self._queue_job(text_a)
        model_a, _ = self._prepare_model(
            text_a, rev_a, sha_a, _distinct_specs()
        )
        _, outcome = self._run_once(job_a, text_a, sha_a, model_a)
        self.assertEqual("completed", outcome)

        text_c = """# 另一部書

## 武帝紀

曹操字孟德，沛國譙人也。太祖少機警，有權數，而任俠放蕩不治行業。

## 吳主傳

孫權字仲謀，吳郡富春人也。兄策既定諸郡，權年十五以為陽羨長。
"""
        specs_c = [
            {
                "translation": "曹操，字孟德，少機警而任俠放蕩。",
                "entities": [
                    {"name": "曹操", "type": "person", "mention": "曹操"},
                ],
                "event": {"type": "other", "title": "曹操少年任俠"},
            },
            {
                "translation": "孫權，字仲謀，年十五為陽羨長。",
                "entities": [
                    {"name": "孫權", "type": "person", "mention": "孫權"},
                ],
                "event": {"type": "appointment", "title": "孫權為陽羨長"},
            },
        ]
        job_c, rev_c, sha_c = self._queue_job(text_c)
        model_c, _ = self._prepare_model(text_c, rev_c, sha_c, specs_c)
        _, outcome = self._run_once(job_c, text_c, sha_c, model_c)
        self.assertEqual("completed", outcome)

        with psycopg.connect(self.database_url) as conn:
            rows = conn.execute(
                "SELECT artifact_sha256, publication_sequence "
                "FROM chronicle.canonical_catalogs "
                "ORDER BY publication_sequence"
            ).fetchall()
            self.assertEqual(2, len(rows))
            self.assertLess(rows[0][1], rows[1][1])
            latest = resolve_publish.read_latest_catalog(conn)
            self.assertEqual(rows[1][0], resolve_publish.sha256_json(latest))
            c_catalog = conn.execute(
                """
                SELECT payload->>'catalog_sha256' FROM chronicle.ingestion_outputs
                WHERE job_id = %s AND artifact_type = %s
                """,
                (job_c, "canonical-catalog"),
            ).fetchone()[0]
            self.assertEqual(rows[1][0], c_catalog)

    # -- immutability: same revision, changed content is rejected ----------

    def test_same_revision_changed_content_is_rejected(self) -> None:
        text = TEXT_DISTINCT
        job_id, revision_id, source_sha = self._queue_job(text)
        model, _ = self._prepare_model(
            text, revision_id, source_sha, _distinct_specs()
        )
        plan, requests = self._planned_requests(text, job_id, source_sha)
        with psycopg.connect(self.database_url) as conn:
            control_plane.claim_job(
                conn, worker="worker-t13", lease_seconds=300, job_id=job_id
            )
            conn.commit()
        self._advance_running(job_id, "structure", "segment")
        self.assertEqual(
            "ok",
            stage.execute_chapter_structure(
                self.database_url, job_id=job_id, worker="worker-t13",
                plan=plan, text=text, lease_seconds=300,
            ),
        )
        self.assertEqual(
            "ok",
            stage.execute_chapter_segment(
                self.database_url, job_id=job_id, worker="worker-t13",
                plan=plan, requests=requests, lease_seconds=300,
            ),
        )
        self._advance_running(job_id, "extract")
        self.assertEqual(
            "ok",
            stage.execute_chapter_extract(
                self.database_url, job_id=job_id, worker="worker-t13",
                plan=plan, requests=requests, model=model,
                limits=chapter_contract.ChapterLimits(), lease_seconds=300,
            ),
        )
        with psycopg.connect(self.database_url) as conn:
            entries = chapter_store.read_accepted_chapters(conn, job_id=job_id)
            self.assertEqual(2, len(entries))
            chunk_id = conn.execute(
                """
                SELECT chunk_id FROM chronicle.ingestion_chunks
                WHERE job_id = %s AND chunk_index = 0
                """,
                (job_id,),
            ).fetchone()[0]
            run_id = conn.execute(
                """
                SELECT run_id FROM chronicle.ingestion_chunk_runs
                WHERE chunk_id = %s ORDER BY attempt DESC LIMIT 1
                """,
                (chunk_id,),
            ).fetchone()[0]
        entry = entries[0]
        request = requests[0]
        candidate = json.loads(json.dumps(entry["artifact"]["candidate"]))
        candidate["translation"]["blocks"][0]["text"] += "後人補一筆。"
        producing_run = {
            "run_id": run_id,
            "model": model.name,
            "prompt_schema_version": "c2r1-chapter-prompt-v1",
        }
        with psycopg.connect(self.database_url) as conn:
            with self.assertRaises(PersistenceConflict) as ctx:
                chapter_store.record_accepted_chapter_fenced(
                    conn, job_id=job_id, chunk_id=chunk_id,
                    worker="worker-t13", request=request,
                    candidate=candidate,
                    producing_run=producing_run,
                )
            conn.rollback()
        self.assertIn("immutable_artifact_conflict", str(ctx.exception))
        with psycopg.connect(self.database_url) as conn:
            entries_after = chapter_store.read_accepted_chapters(
                conn, job_id=job_id
            )
            self.assertEqual(
                entry["artifact_sha256"], entries_after[0]["artifact_sha256"]
            )


    # -- fail closed: chapter model without a revision source -----------

    def test_chapter_model_without_source_fails_before_any_stage(self) -> None:
        text = TEXT_DISTINCT
        job_id, _, _ = self._queue_job(text)

        class _StubModel:
            name = "stub-chapter-model"

            def complete(self, prompt: str) -> str:  # pragma: no cover
                raise AssertionError("must never be called")

        result = worker.run_once(
            self.database_url, worker="worker-t13",
            chapter_model=_StubModel(),
            chapter_limits=chapter_contract.ChapterLimits(),
            job_id=job_id,
        )
        self.assertIsNotNone(result)
        self.assertEqual("failed", result[1])
        with psycopg.connect(self.database_url) as conn:
            status, error = conn.execute(
                "SELECT status, error FROM chronicle.ingestion_jobs WHERE job_id = %s",
                (job_id,),
            ).fetchone()
            self.assertEqual("failed", status)
            self.assertIn("without a revision source", error)
            # No stage ran and no fake output was invented.
            stages = dict(
                conn.execute(
                    "SELECT stage, status FROM chronicle.ingestion_job_stages "
                    "WHERE job_id = %s",
                    (job_id,),
                ).fetchall()
            )
            self.assertTrue(all(value == "pending" for value in stages.values()))
            self.assertEqual(
                0,
                conn.execute(
                    "SELECT count(*) FROM chronicle.ingestion_chunks WHERE job_id = %s",
                    (job_id,),
                ).fetchone()[0],
            )
            self.assertEqual(
                0,
                conn.execute(
                    "SELECT count(*) FROM chronicle.ingestion_outputs WHERE job_id = %s",
                    (job_id,),
                ).fetchone()[0],
            )

    # -- publish fence: an expired lease cannot publish after lock wait ----

    def test_publish_rejects_expired_lease_without_writes(self) -> None:
        text = TEXT_DISTINCT
        job_id, revision_id, source_sha = self._queue_job(text)
        model, _ = self._prepare_model(
            text, revision_id, source_sha, _distinct_specs()
        )
        plan, requests = self._planned_requests(text, job_id, source_sha)
        with psycopg.connect(self.database_url) as conn:
            control_plane.claim_job(
                conn, worker="worker-t13", lease_seconds=300, job_id=job_id
            )
            conn.commit()
        self._advance_running(
            job_id, "structure", "segment", "extract", "assemble", "resolve",
            "publish",
        )
        for fn, kwargs, kind in (
            (
                stage.execute_chapter_structure,
                {"plan": plan, "text": text},
                "ok",
            ),
            (
                stage.execute_chapter_segment,
                {"plan": plan, "requests": requests},
                "ok",
            ),
            (
                stage.execute_chapter_extract,
                {
                    "plan": plan, "requests": requests, "model": model,
                    "limits": chapter_contract.ChapterLimits(),
                },
                "ok",
            ),
            (stage.execute_chapter_assemble, {"plan": plan}, "assembled"),
            (stage.execute_chapter_resolve, {"plan": plan}, "ok"),
        ):
            result = fn(
                self.database_url, job_id=job_id, worker="worker-t13",
                lease_seconds=300, **kwargs,
            )
            if kind == "assembled":
                self.assertIsInstance(result, tuple)
                self.assertIn("bundle", result[0])
            else:
                self.assertEqual(kind, result)
        # The lock wait outlives the lease without any takeover: the
        # owner is unchanged but the expiry already passed.
        with psycopg.connect(self.database_url) as conn:
            conn.execute(
                "UPDATE chronicle.ingestion_jobs "
                "SET lease_expires_at = now() - interval '1 second' "
                "WHERE job_id = %s",
                (job_id,),
            )
            conn.commit()
        with psycopg.connect(self.database_url) as conn:
            with self.assertRaises(LeaseLost):
                resolve_publish.publish_chapters(
                    conn, job_id=job_id, worker="worker-t13"
                )
            conn.rollback()
            self.assertEqual(
                0,
                conn.execute(
                    "SELECT count(*) FROM chronicle.canonical_catalogs"
                ).fetchone()[0],
            )
            self.assertEqual(
                0,
                conn.execute(
                    "SELECT count(*) FROM chronicle.chapter_publications"
                ).fetchone()[0],
            )


if __name__ == "__main__":
    unittest.main()
