"""PostgreSQL 18 integration tests for the C2-R3-T08 person-state publication.

Proves the production chapter chain freezes, reviews and publishes the 0.3
phase evidence in the same unique transaction as the catalog, every complete
chapter and the reading index:

- a fresh 0.3 revision extracts/assembles/resolves; identity Resolution
  finishes first and the job then parks in ``needs_review`` on one
  ``chapter_state_evidence`` package per chapter;
- once every package is terminal the same job resumes through
  publish/present and exposes exactly one immutable person-state manifest
  whose units bind the reading stream and whose reviewed assessment is
  persisted in the same transaction;
- replaying the same accepted artifacts, assessments and mapping reuses the
  identical manifest and assessment without a second model call;
- a fault injected after the catalog/chapters/reading index while writing the
  person-state manifest leaves zero public content (no catalog, chapter,
  stream, manifest or assessment), and a clean retry then succeeds.

The 0.3 joint provider is the explicit fixture-pack test injection
(``FixturePersonStateChapterModel``); production model selection is covered by
``test_person_state_provider_unit.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
for path in (HERE, HERE.parent / "persistence"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import chapter_contract  # noqa: E402
import chapter_store  # noqa: E402
import control_plane  # noqa: E402
import person_state_review  # noqa: E402
from common import PersistenceError  # noqa: E402
from migrations import apply_migrations  # noqa: E402

import chapter_stage as stage  # noqa: E402
import resolve_publish as R  # noqa: E402
import test_reading_pipeline_postgres as base  # noqa: E402


TEXT = """# 測試書

## 先主傳

劉備字玄德，涿郡涿縣人也。公孫瓚舉備為別部司馬。

## 周瑜傳

周瑜字公瑾，廬江舒人也。孫策與瑜為友。
"""


def _specs() -> list[dict]:
    return [
        {
            "translation": "劉備，字玄德，公孫瓚任其為別部司馬。",
            "entities": [
                {"name": "劉備", "type": "person", "mention": "劉備"},
                {"name": "公孫瓚", "type": "person", "mention": "公孫瓚"},
            ],
            "event": {"type": "appointment", "title": "公孫瓚舉劉備"},
        },
        {
            "translation": "周瑜，字公瑾，與孫策為友。",
            "entities": [
                {"name": "周瑜", "type": "person", "mention": "周瑜"},
                {"name": "孫策", "type": "person", "mention": "孫策"},
            ],
            "event": {"type": "cultural", "title": "孫策周瑜為友"},
        },
    ]


class PersonStatePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control_url = base._control_url()

    setUp = base.ReadingPipelinePostgresTests.setUp
    tearDown = base.ReadingPipelinePostgresTests.tearDown
    _queue_job = base.ReadingPipelinePostgresTests._queue_job
    _run_once = base.ReadingPipelinePostgresTests._run_once
    _public_counts = base.ReadingPipelinePostgresTests._public_counts
    _reading_stream_row = base.ReadingPipelinePostgresTests._reading_stream_row

    # -- helpers --------------------------------------------------------

    def _prepare_person_state_model(self, text, revision_id, source_sha):
        import fixture_model

        plan = base._plan_for(text, revision_id, source_sha)
        pack = base._pack_payload(plan, revision_id, _specs())
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as handle:
            json.dump(pack, handle, ensure_ascii=False)
            path = handle.name
        try:
            model = fixture_model.models_from_person_state_chapter_fixture_pack(path)
        finally:
            os.unlink(path)
        return model, plan

    def _open_person_state_reviews(self, job_id):
        with psycopg.connect(self.database_url) as conn:
            rows = conn.execute(
                "SELECT review_id, payload FROM chronicle.review_items"
                " WHERE job_id = %s AND payload->>'scope' = 'person_state'"
                " ORDER BY created_at, review_id",
                (job_id,),
            ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def _person_state_plan(self, job_id):
        with psycopg.connect(self.database_url) as conn:
            payload = R.read_person_state_plan_output(conn, job_id=job_id)
        self.assertIsNotNone(payload)
        return payload["plan"]

    def _approve_person_state(self, job_id):
        plan = self._person_state_plan(job_id)
        reviews = self._open_person_state_reviews(job_id)
        self.assertTrue(reviews)
        with psycopg.connect(self.database_url) as conn:
            for review_id, payload in reviews:
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
                        "rationale": "整章阶段依据逐项核对原文后确认。",
                        "overrides": [
                            {
                                "candidate_id": candidate["candidate_key"],
                                "assessment": "supported",
                                "rationale": "直接原文支持。",
                            }
                            for candidate in package["candidates"]
                        ],
                    },
                )
                conn.commit()
            control_plane.resume_job(conn, job_id=job_id)
            conn.commit()

    def _drive_to_park(self, text=TEXT):
        job_id, revision_id, source_sha = self._queue_job(text)
        model, plan = self._prepare_person_state_model(text, revision_id, source_sha)
        _claimed, outcome = self._run_once(job_id, text, source_sha, model)
        if outcome != "needs_review":
            with psycopg.connect(self.database_url) as conn:
                detail = control_plane.get_job_detail(conn, job_id=job_id)
            self.fail(f"expected needs_review, got {outcome}: {detail}")
        self.args = (job_id, text, source_sha, model, plan)
        return job_id

    # -- tests ----------------------------------------------------------

    def test_resolve_parks_on_state_review_then_publishes_manifest(self):
        job_id = self._drive_to_park()
        job, text, source_sha, model, _plan = self.args
        package_plan = self._person_state_plan(job_id)
        reviews = self._open_person_state_reviews(job_id)
        self.assertEqual(2, len(reviews))
        self.assertEqual(
            {item["chapter_id"] for item in package_plan["packages"]},
            {payload["chapter_id"] for _row, payload in reviews},
        )
        calls_before = getattr(model, "calls", None)

        self._approve_person_state(job_id)
        _claimed, outcome = self._run_once(job_id, text, source_sha, model)
        if outcome != "completed":
            with psycopg.connect(self.database_url) as conn:
                detail = control_plane.get_job_detail(conn, job_id=job_id)
            self.fail(f"expected completed, got {outcome}: {detail['error']}::{detail['stages']}")

        with psycopg.connect(self.database_url) as conn:
            manifest = conn.execute(
                """
                SELECT m.manifest_sha, m.stream_id, m.chapter_publication_ids,
                       m.assessment_hashes
                FROM chronicle.person_state_manifests m
                """
            ).fetchall()
            self.assertEqual(1, len(manifest))
            manifest_sha, stream_id, publications, assessments = manifest[0]
            self.assertEqual(1, len(assessments))
            self.assertEqual(len(publications), 2)
            people = conn.execute(
                "SELECT count(*) FROM chronicle.person_state_unit_people"
                " WHERE manifest_sha = %s",
                (manifest_sha,),
            ).fetchone()[0]
            items = conn.execute(
                "SELECT count(*) FROM chronicle.person_state_items"
                " WHERE manifest_sha = %s",
                (manifest_sha,),
            ).fetchone()[0]
            self.assertGreaterEqual(people, 1)
            self.assertGreaterEqual(items, 1)
            (assessment_sha,) = assessments
            assessed = conn.execute(
                "SELECT base_catalog_sha FROM chronicle.person_state_assessments"
                " WHERE assessment_sha = %s",
                (assessment_sha,),
            ).fetchone()
            self.assertIsNotNone(assessed)
            catalog_sha = conn.execute(
                "SELECT artifact_sha256 FROM chronicle.canonical_catalogs"
            ).fetchone()[0]
            self.assertEqual(catalog_sha, assessed[0])

        # The published reading stream and the manifest bind one revision.
        with psycopg.connect(self.database_url) as conn:
            stream = conn.execute(
                "SELECT chapter_publication_ids FROM chronicle.reading_streams"
                " WHERE stream_id = %s",
                (stream_id,),
            ).fetchone()
        self.assertEqual(
            {str(value) for value in stream[0]},
            {str(value) for value in publications},
        )
        if calls_before is not None:
            self.assertEqual(calls_before, model.calls)

    def test_reviewed_source_states_reach_composite_context(self):
        import narrative_store

        job_id = self._drive_to_park()
        job, text, source_sha, model, plan = self.args
        self._approve_person_state(job_id)
        self.assertEqual("completed", self._run_once(job_id, text, source_sha, model)[1])
        with psycopg.connect(self.database_url) as conn:
            published = chapter_store.list_published_chapters(
                conn, job_id=job_id, limit=100
            )
            descriptors = narrative_store.source_descriptors(
                conn, publication_ids=[item["publication_id"] for item in published]
            )
        facts = [
            fact
            for source in descriptors["sources"]
            for fact in source["reviewed_person_states"]
        ]
        self.assertTrue(facts, "published 0.3 source must expose reviewed state facts")
        for fact in facts:
            self.assertTrue(fact["phase_ids"])
            self.assertIn(fact["certainty"], ("clear", "uncertain"))
            self.assertIn("source_facts", fact)
        context = narrative_store.build_context(
            descriptors, lambda _job: (text, source_sha)
        )
        self.assertTrue(
            any(source["reviewed_person_states"] for source in context["sources"])
        )

    def test_replay_reuses_manifest_without_regeneration(self):
        import reading_projection

        job_id = self._drive_to_park()
        job, text, source_sha, model, plan = self.args
        self._approve_person_state(job_id)
        self.assertEqual("completed", self._run_once(job_id, text, source_sha, model)[1])
        with psycopg.connect(self.database_url) as conn:
            first = conn.execute(
                "SELECT manifest_sha FROM chronicle.person_state_manifests"
            ).fetchone()[0]
            first_assessment = conn.execute(
                "SELECT assessment_sha FROM chronicle.person_state_assessments"
            ).fetchone()[0]
            accepted = chapter_store.read_accepted_chapters(conn, job_id=job_id)
            published = chapter_store.list_published_chapters(
                conn, job_id=job_id, limit=100
            )
            catalog = R.read_latest_catalog(conn)
            revision_id = conn.execute(
                "SELECT revision_id FROM chronicle.ingestion_jobs WHERE job_id = %s",
                (job_id,),
            ).fetchone()[0]
            plan_payload = R.read_person_state_plan_output(conn, job_id=job_id)
            assembled = conn.execute(
                """
                SELECT payload FROM chronicle.ingestion_outputs
                WHERE job_id = %s AND artifact_type = %s
                ORDER BY created_at DESC LIMIT 1
                """,
                (job_id, "assembled-source-bundle"),
            ).fetchone()[0]
            before = {
                table: conn.execute(f"SELECT count(*) FROM chronicle.{table}").fetchone()[0]
                for table in (
                    "person_state_manifests",
                    "person_state_unit_people",
                    "person_state_items",
                    "person_state_disagreements",
                    "person_state_assessments",
                )
            }
        publication_by_chapter = {
            item["chapter_id"]: item["publication_id"] for item in published
        }
        bundle_label = R.new_bundle_label(revision_id)
        projection = reading_projection.compile_reading_projection(
            accepted_artifacts=[entry["artifact"] for entry in accepted],
            chapter_plan=plan,
            catalog=catalog,
            stream_id=R.reading_stream_seed(revision_id),
            publication_by_chapter=publication_by_chapter,
            bundle_label=bundle_label,
        )
        # Replaying the same compiled bytes and reviewed decisions must reuse
        # the identical manifest/assessment and append no rows.
        with psycopg.connect(self.database_url) as conn:
            result = R.persist_person_state_publication(
                conn,
                job_id=job_id,
                plan=plan_payload["plan"],
                catalog=catalog,
                catalog_sha256=R.sha256_json(catalog),
                bundle_label=bundle_label,
                revision_id=revision_id,
                projection=projection,
                chapter_publication_ids=R._ordered_chapter_publications(
                    projection, publication_by_chapter
                ),
                publication_by_chapter=publication_by_chapter,
                evidence=assembled["person_states"],
            )
            conn.commit()
            after = {
                table: conn.execute(f"SELECT count(*) FROM chronicle.{table}").fetchone()[0]
                for table in before
            }
        self.assertEqual(first, result["person_state_manifest_sha"])
        self.assertEqual(first_assessment, result["person_state_assessment_sha"])
        self.assertEqual(before, after)

    def test_manifest_fault_rolls_back_all_public_content(self):
        from unittest import mock

        job_id = self._drive_to_park()
        job, text, source_sha, model, plan = self.args
        self._approve_person_state(job_id)
        with mock.patch.object(
            R,
            "persist_person_state_publication",
            side_effect=PersistenceError("injected person-state publish fault"),
        ):
            self.assertEqual(
                "failed", self._run_once(job_id, text, source_sha, model)[1]
            )
        with psycopg.connect(self.database_url) as conn:
            counts = self._public_counts()
            counts["person_state_manifests"] = conn.execute(
                "SELECT count(*) FROM chronicle.person_state_manifests"
            ).fetchone()[0]
            counts["person_state_assessments"] = conn.execute(
                "SELECT count(*) FROM chronicle.person_state_assessments"
            ).fetchone()[0]
            self.assertEqual(0, counts["canonical_catalogs"])
            self.assertEqual(0, counts["chapter_publications"])
            self.assertEqual(0, counts["reading_streams"])
            self.assertEqual(0, counts["person_state_manifests"])
            self.assertEqual(0, counts["person_state_assessments"])
            control_plane.retry_job(conn, job_id=job_id)
            conn.commit()
        # A clean retry after the injected fault publishes the complete set.
        self.assertEqual("completed", self._run_once(job_id, text, source_sha, model)[1])
        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(
                1,
                conn.execute(
                    "SELECT count(*) FROM chronicle.person_state_manifests"
                ).fetchone()[0],
            )
            self.assertEqual(
                1,
                conn.execute(
                    "SELECT count(*) FROM chronicle.reading_streams"
                ).fetchone()[0],
            )


if __name__ == "__main__":
    unittest.main()
