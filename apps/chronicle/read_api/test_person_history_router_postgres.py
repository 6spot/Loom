"""PostgreSQL coverage for the C3-T13 public person-history reader."""

from __future__ import annotations

import json
import sys
import unittest
import uuid
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve()
WORKER = HERE.parent.parent / "worker"
PERSISTENCE = HERE.parent.parent / "persistence"
for path in (WORKER, PERSISTENCE, HERE.parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import control_plane  # noqa: E402
import person_history_store  # noqa: E402
import router  # noqa: E402
import staged_pipeline_fixture  # noqa: E402
import test_person_history_pipeline_postgres as person_pipeline  # noqa: E402
from person_history_repository import PersonHistoryReadRepository  # noqa: E402
from repository import ChronicleReadRepository  # noqa: E402


class MultiPhasePersonHistoryModel(person_pipeline.PersonHistoryTestModel):
    """Split the real staged source facts into independently readable phases."""

    def _summary(self, context: dict) -> dict:
        sources = context["sources"]
        source_by_id = {source["source_id"]: source for source in sources}
        approved = [
            item
            for item in context["approved_conclusions"]
            if item.get("source_id") in source_by_id
        ]
        phases = []
        conclusions = []
        positions = context.get("main_history_positions") or []
        mapping_ids = [item["id"] for item in positions]
        for index, item in enumerate(approved):
            phase_id = f"phase_{index + 1:03}"
            source = source_by_id[item["source_id"]]
            mapping_status = (
                "ambiguous"
                if len(mapping_ids) > 1
                else "mapped"
                if mapping_ids
                else "unmapped"
            )
            phases.append(
                {
                    "id": phase_id,
                    "label": f"{source.get('title') or '人物经历'} · 阶段 {index + 1}",
                    "year": None,
                    "period": None,
                    "basis": [source["evidence"][0]["id"]],
                    "relation_to_previous": "uncertain" if not phases else "after",
                    "mapping_status": mapping_status,
                    "mapping_position_ids": mapping_ids,
                    "mapping_reason": (
                        "当前没有足够可靠的主历史对应位置。"
                        if not mapping_ids
                        else "仅保留程序提供的可靠主历史位置。"
                    ),
                }
            )
            dimension = item.get("dimension")
            value = item.get("value")
            if dimension == "affiliation":
                dimension, value = "action", None
            if dimension in {"office", "title", "allegiance"} and not isinstance(value, str):
                dimension, value = "action", None
            conclusions.append(
                {
                    "id": f"conclusion_{index + 1:03}",
                    "person_id": context["target"]["person_id"],
                    "dimension": dimension,
                    "phase_ids": [phase_id],
                    "text": item.get("text") or "来源明确记载了这一阶段的内容。",
                    "value": value,
                    "certainty": item.get("certainty")
                    if item.get("certainty") in {"clear", "uncertain"}
                    else "uncertain",
                    "qualification": item.get("qualification")
                    if item.get("qualification")
                    in {"ordinary", "recommendation", "self_designation", "posthumous", "reported"}
                    else "ordinary",
                    "event_id": None,
                    "related_entity_ids": [],
                    "evidence": [
                        {
                            "id": source["evidence"][0]["id"],
                            "relation": "support",
                            "attribution": "已发布原章",
                            "note": "原文证据与批准来源结论相互绑定。",
                        }
                    ],
                    "approved_conclusion_ids": [item["id"]],
                }
            )
        if len(phases) < 2:
            raise AssertionError("staged source fixture did not expose two person phases")
        return {
            "schema": "chronicle.person-history-summary",
            "version": "0.1",
            "person_id": context["target"]["person_id"],
            "title": "周瑜生平概况",
            "overview": "以下概况仅整理当前收录资料明确记载的经历。",
            "birth": None,
            "death": None,
            "coverage": {
                "statement": "根据当前收录资料整理的经历",
                "exhaustive": False,
                "source_ids": [source["source_id"] for source in sources],
                "publication_ids": [source["publication_id"] for source in sources],
            },
            "phases": phases,
            "conclusions": conclusions,
        }


class PersonHistoryRouterPostgresTests(unittest.TestCase):
    """Run the real T12 publication path, then exercise its read boundary."""

    AUTO_APPROVE_PERSON_STATE = True

    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = person_pipeline.base._control_url()

    setUp = person_pipeline.base.ReadingPipelinePostgresTests.setUp
    tearDown = person_pipeline.base.ReadingPipelinePostgresTests.tearDown
    _queue_job = person_pipeline.base.ReadingPipelinePostgresTests._queue_job
    _prepare_model = person_pipeline.base.ReadingPipelinePostgresTests._prepare_model
    _run_once = person_pipeline.base.ReadingPipelinePostgresTests._run_once
    _approve_person_state = person_pipeline.base.ReadingPipelinePostgresTests._approve_person_state

    def _publish_person_history(
        self,
        *,
        text: str | None = None,
        model_cls=person_pipeline.PersonHistoryTestModel,
    ) -> tuple[str, dict, dict]:
        text = text or person_pipeline.base.TEXT_DISTINCT
        source_job, revision_id, source_sha = self._queue_job(text)
        source_model, _plan = self._prepare_model(text, revision_id, source_sha)
        self.assertEqual(
            "completed",
            self._run_once(source_job, text, source_sha, source_model)[1],
        )

        with psycopg.connect(self.database_url) as conn:
            choices = person_history_store.list_person_choices(conn)
            person = next(item for item in choices["items"] if "周瑜" in item["name"])
            source_ids = [
                item["publication_id"]
                for item in person_history_store.narrative_store.list_source_choices(conn)["items"]
            ]
            status, _content_type, body = person_pipeline.studio_jobs.dispatch_jobs(
                conn,
                control_plane,
                method="POST",
                path="/api/v1/studio/jobs/person-history",
                body=json.dumps(
                    {
                        "person_id": person["person_id"],
                        "catalog_sha": choices["catalog_sha"],
                        "publication_ids": source_ids,
                    }
                ).encode(),
            )
            self.assertEqual(201, status, body)
            person_job = uuid.UUID(json.loads(body)["job"]["job_id"])

        model = model_cls()
        self.assertEqual(
            "needs_review",
            self._run_once(
                person_job,
                text,
                source_sha,
                source_model,
                narrative_model=model,
            )[1],
        )
        with psycopg.connect(self.database_url) as conn:
            summary = person_history_store.read_candidate(conn, person_job, "summary")
            person_history_store.decide(
                conn,
                review_id=summary["review_id"],
                candidate_sha=summary["candidate_sha"],
                decision="approve",
                rationale="测试读取边界前核对摘要。",
                reviewed_conclusion_ids=[
                    item["id"] for item in summary["candidate"]["conclusions"]
                ],
            )
            control_plane.resume_job(conn, job_id=person_job)
        self.assertEqual(
            "needs_review",
            self._run_once(
                person_job,
                text,
                source_sha,
                source_model,
                narrative_model=model,
            )[1],
        )
        with psycopg.connect(self.database_url) as conn:
            prose = person_history_store.read_candidate(conn, person_job, "prose")
            reviewed = sorted(
                {
                    conclusion_id
                    for paragraph in prose["candidate"]["paragraphs"]
                    for segment in paragraph["segments"]
                    for conclusion_id in segment["conclusion_ids"]
                }
            )
            person_history_store.decide(
                conn,
                review_id=prose["review_id"],
                candidate_sha=prose["candidate_sha"],
                decision="approve",
                rationale="测试读取边界前核对正文。",
                reviewed_conclusion_ids=reviewed,
            )
            control_plane.resume_job(conn, job_id=person_job)
        self.assertEqual(
            "completed",
            self._run_once(
                person_job,
                text,
                source_sha,
                source_model,
                narrative_model=model,
            )[1],
        )
        with psycopg.connect(self.database_url) as conn:
            publication = person_history_store.read_publication(
                conn, person_id=person["person_id"]
            )
        self.assertIsNotNone(publication)
        return person["person_id"], person, publication

    def _dispatch(self, method: str, path: str, query: str = ""):
        with psycopg.connect(self.database_url) as conn:
            return router.dispatch(
                ChronicleReadRepository(conn), method, path, query
            )

    def test_published_versions_pages_mapping_and_evidence_are_read_only(self) -> None:
        person_id, _person, publication = self._publish_person_history()
        version = publication["publication_version"]
        prefix = f"/v0/entities/{person_id}/history"

        status, metadata = self._dispatch("GET", prefix)
        self.assertEqual(200, status)
        self.assertEqual("published", metadata["status"])
        self.assertEqual(version, metadata["publication"]["person_history_version"])
        self.assertEqual(
            "根据当前收录资料整理的经历",
            metadata["publication"]["coverage"]["statement"],
        )
        self.assertEqual(
            metadata["publication"]["first_paragraph_id"],
            publication["paragraphs"][0]["id"],
        )
        # Metadata and prose expose handles, not the complete evidence index.
        self.assertNotIn("evidence", metadata["publication"])
        self.assertNotIn("evidence", metadata["publication"]["first_paragraph"])

        status, page = self._dispatch(
            "GET", f"{prefix}/paragraphs", f"version={version}&limit=1"
        )
        self.assertEqual(200, status)
        self.assertEqual(version, page["person_history_version"])
        self.assertEqual(1, len(page["paragraphs"]))
        self.assertEqual(0, page["start"])
        self.assertEqual(page["paragraphs"][0]["id"], page["first_paragraph_id"])
        self.assertNotIn("evidence", page["paragraphs"][0])
        paragraph = page["paragraphs"][0]
        self.assertTrue(paragraph["actions"])
        self.assertFalse(paragraph["states"])
        self.assertTrue(
            all(
                item["dimension"] in {"office", "title", "allegiance"}
                for item in paragraph["states"]
            )
        )

        conclusion_id = publication["conclusions"][0]["id"]
        status, conclusion = self._dispatch(
            "GET",
            f"{prefix}/conclusions/{conclusion_id}",
            f"version={version}",
        )
        self.assertEqual(200, status)
        self.assertEqual(conclusion_id, conclusion["conclusion"]["id"])
        self.assertTrue(conclusion["source_citations"])
        citation = conclusion["source_citations"][0]
        self.assertTrue(citation["publication_id"])
        self.assertTrue(citation["anchor_id"])
        self.assertIn(
            f"/api/v1/public/chapters/{citation['publication_id']}/sources/",
            citation["source"]["path"],
        )

        # The route is fixed to the requested immutable version and fails
        # closed for cross-person versions, unknown paragraphs and bad pages.
        other_person = str(uuid.uuid7())
        for path, query, expected in (
            (f"{prefix}/paragraphs", f"version={'0' * 64}", 404),
            (f"{prefix}/paragraphs", f"version={version}&at=pp_{'0' * 24}", 404),
            (f"{prefix}/paragraphs", f"version={version}&start=99", 400),
            (f"/v0/entities/{other_person}/history/paragraphs", f"version={version}", 404),
            (f"{prefix}/paragraphs", "version=draft", 400),
        ):
            status, _payload = self._dispatch("GET", path, query)
            self.assertEqual(expected, status, (path, query))
        status, _payload = self._dispatch("POST", prefix)
        self.assertEqual(405, status)

    def test_person_without_publication_returns_an_empty_state(self) -> None:
        self._publish_person_history()
        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                """
                SELECT r.canonical_id::text
                FROM chronicle.canonical_entity_representations r
                JOIN chronicle.staged_entities e USING (bundle_label, record_ref)
                WHERE e.payload->>'type' = 'person'
                  AND NOT EXISTS (
                      SELECT 1 FROM chronicle.person_histories h
                      WHERE h.person_id = r.canonical_id
                  )
                ORDER BY r.canonical_id
                LIMIT 1
                """
            ).fetchone()
        self.assertIsNotNone(row)
        status, payload = self._dispatch(
            "GET", f"/v0/entities/{row[0]}/history"
        )
        self.assertEqual(200, status)
        self.assertEqual("empty", payload["status"])
        self.assertIsNone(payload["publication"])
        self.assertTrue(payload["empty"])

    def test_real_staged_response_retains_multiple_person_phases(self) -> None:
        person_id, _person, publication = self._publish_person_history(
            text=staged_pipeline_fixture.TEXT,
            model_cls=MultiPhasePersonHistoryModel,
        )
        prefix = f"/v0/entities/{person_id}/history"
        status, metadata = self._dispatch("GET", prefix)
        self.assertEqual(200, status)
        phases = metadata["publication"]["phases"]
        self.assertGreaterEqual(len(phases), 2)
        self.assertEqual(
            {"unmapped"},
            {phase["mapping_status"] for phase in phases},
        )

        status, page = self._dispatch(
            "GET",
            f"{prefix}/paragraphs",
            f"version={publication['publication_version']}&limit=50",
        )
        self.assertEqual(200, status)
        self.assertGreaterEqual(page["returned"], 2)
        self.assertEqual(phases[0]["id"], page["paragraphs"][0]["phase_id"])
        self.assertEqual(phases[1]["id"], page["paragraphs"][1]["phase_id"])
        self.assertTrue(any(item["states"] for item in page["paragraphs"]))
        self.assertTrue(any(item["actions"] for item in page["paragraphs"]))
        self.assertTrue(
            all(
                item["dimension"] in {"office", "title", "allegiance"}
                for paragraph in page["paragraphs"]
                for item in paragraph["states"]
            )
        )


class PersonHistoryMappingUnitTests(unittest.TestCase):
    """Keep ambiguous main-history candidates lossless at the read boundary."""

    def test_ambiguous_locator_keeps_every_candidate(self) -> None:
        class MappingRepository(PersonHistoryReadRepository):
            def _resolve_main_locator(self, *, version: str, paragraph_id: str):
                return {
                    "requested_version": version,
                    "requested_paragraph_id": paragraph_id,
                    "source_version": version,
                    "source_paragraph_id": paragraph_id,
                    "source_phase_id": "hphase_early",
                }

        version = "a" * 64
        snapshot = {
            "mapping_rows": [
                {
                    "person_phase_id": "phase_early",
                    "mapping_no": 0,
                    "mapping_status": "ambiguous",
                    "main_history_version_sha": version,
                    "main_history_paragraph_id": "hp_early_position",
                    "main_history_phase_id": "hphase_early",
                    "reason": "保留两个明确候选。",
                    "evidence_conclusion_ids": [],
                    "payload": {"position_id": "history_early_a"},
                },
                {
                    "person_phase_id": "phase_early",
                    "mapping_no": 1,
                    "mapping_status": "ambiguous",
                    "main_history_version_sha": version,
                    "main_history_paragraph_id": "hp_early_alternate",
                    "main_history_phase_id": "hphase_early",
                    "reason": "保留两个明确候选。",
                    "evidence_conclusion_ids": [],
                    "payload": {"position_id": "history_early_b"},
                },
            ]
        }
        mapping = MappingRepository(None)._mapping_for_locator(
            snapshot,
            main_version=version,
            paragraph_id="hp_early_position",
        )
        self.assertEqual("ambiguous", mapping["status"])
        self.assertEqual(
            {"hp_early_position", "hp_early_alternate"},
            {item["paragraph_id"] for item in mapping["matches"][0]["targets"]},
        )
        self.assertEqual(
            {"history_early_a", "history_early_b"},
            {item["position_id"] for item in mapping["matches"][0]["targets"]},
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
