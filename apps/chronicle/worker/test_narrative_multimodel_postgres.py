"""PostgreSQL proof of the narrative generation/comparison/review graph."""
from __future__ import annotations

import json
import sys
import unittest
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
for path in (HERE, HERE.parent / "persistence", HERE.parent / "read_api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import psycopg

import control_plane
import narrative_store
import studio_jobs
from test_narrative_contract import drafts
from test_narrative_pipeline_postgres import NarrativeTestModel
import test_reading_pipeline_postgres as base


class _Provider:
    def __init__(self, owner, name):
        self.owner = owner
        self.name = name

    def complete(self, prompt):
        stage = prompt.split("\nSTAGE=", 1)[1].split("\n", 1)[0]
        self.owner.calls.append((stage, self.name))
        if stage in ("facts", "facts_generate"):
            context = json.loads(prompt.split("\nINPUT=", 1)[1])
            result, _ = drafts(context)
        elif stage in ("prose", "prose_generate"):
            context = json.loads(
                prompt.split("\nINPUT=", 1)[1].split("\nAPPROVED_CONCLUSIONS=", 1)[0]
            )
            _, result = drafts(context)
            result["navigation"] = [{
                "label": "测试时段",
                "first_paragraph_id": result["paragraphs"][0]["id"],
                "last_paragraph_id": result["paragraphs"][-1]["id"],
                "items": [
                    {key: entry[key] for key in ("paragraph_id", "label", "reason")}
                    for entry in result["entry_points"]
                ],
            }]
        else:
            candidates = json.loads(
                prompt.split("\nCANDIDATES=", 1)[1].split(
                    "\nAPPROVED_CONCLUSIONS=", 1
                )[0]
            )
            candidate_set_sha = prompt.split("\nCANDIDATE_SET_SHA256=", 1)[1].split(
                "\n", 1
            )[0]
            differences = []
            for item in candidates:
                content = item["content"]
                if stage == "facts_compare":
                    conclusion_ids = [fact["id"] for fact in content["conclusions"]]
                else:
                    conclusion_ids = [
                        conclusion_id
                        for paragraph in content["paragraphs"]
                        for segment in paragraph["segments"]
                        for conclusion_id in segment["conclusion_ids"]
                    ]
                differences.append({
                    "candidate_sha256": item["candidate_sha256"],
                    "assessment": "selected" if not differences else "compatible",
                    "rationale": "按冻结来源逐项核对。",
                    "evidence": ["evidence_001"],
                    "conclusion_ids": conclusion_ids,
                })
            result = {
                "schema": "chronicle.narrative-comparison",
                "version": "0.1",
                "candidate_set_sha256": candidate_set_sha,
                "selected_sha256": candidates[0]["candidate_sha256"],
                "selection_rationale": "按具体来源依据选择完整候选。",
                "differences": differences,
            }
        return json.dumps(result, ensure_ascii=False)


class _MultiModels:
    name = "multi-test"
    candidate_version = "0.1"
    max_parallel = 2
    max_step_attempts = 2
    steps = {
        "facts_generate": ("facts_a", "facts_b"),
        "facts_compare": ("comparator",),
        "prose_generate": ("prose_a",),
        "prose_compare": ("comparator",),
    }

    def __init__(self):
        self.calls = []
        names = {slot for slots in self.steps.values() for slot in slots}
        self.providers = {
            (step, slot): _Provider(self, slot)
            for step, slots in self.steps.items()
            for slot in set(slots)
        }
        self._public = {
            "version": "0.1",
            "models": {name: {"model": name} for name in names},
            "steps": {step: list(slots) for step, slots in self.steps.items()},
            "max_parallel": self.max_parallel,
            "max_step_attempts": self.max_step_attempts,
        }

    def complete(self, _prompt):
        raise AssertionError("the legacy joint narrative entry must not be called")

    def model_for(self, step, slot):
        return self.providers[(step, slot)]

    def model_config(self, _step, slot):
        return {"model": slot, "response_format": "json_object"}

    def public_config(self):
        return self._public


class NarrativeMultiModelPostgresTests(unittest.TestCase):
    """Use the same published-source fixture as the existing narrative tests."""

    AUTO_APPROVE_PERSON_STATE = True

    @classmethod
    def setUpClass(cls):
        cls.control_url = base._control_url()

    setUp = base.ReadingPipelinePostgresTests.setUp
    tearDown = base.ReadingPipelinePostgresTests.tearDown
    _queue_job = base.ReadingPipelinePostgresTests._queue_job
    _prepare_model = base.ReadingPipelinePostgresTests._prepare_model
    _run_once = base.ReadingPipelinePostgresTests._run_once
    _approve_person_state = base.ReadingPipelinePostgresTests._approve_person_state

    def _history_job(self):
        text = base.TEXT_DISTINCT
        source_job, revision, source_sha = self._queue_job(text)
        chapter_model, _ = self._prepare_model(text, revision, source_sha)
        self.assertEqual(
            "completed",
            self._run_once(
                source_job, text, source_sha, chapter_model,
                narrative_model=NarrativeTestModel(),
            )[1],
        )
        with psycopg.connect(self.database_url) as conn:
            sources = narrative_store.list_source_choices(conn)
            status, _, body = studio_jobs.dispatch_jobs(
                conn,
                control_plane,
                method="POST",
                path="/api/v1/studio/jobs/history",
                body=json.dumps({
                    "catalog_sha": sources["catalog_sha"],
                    "publication_ids": [item["publication_id"] for item in sources["items"]],
                }).encode(),
            )
        self.assertEqual(201, status, body)
        job = uuid.UUID(json.loads(body)["job"]["job_id"])
        return job, text, source_sha, chapter_model

    def _approve(self, job_id, kind):
        with psycopg.connect(self.database_url) as conn:
            row = narrative_store.read_candidate(conn, job_id, kind)
            narrative_store.decide(
                conn,
                review_id=row["review_id"],
                candidate_sha=row["candidate_sha"],
                decision="approve",
                rationale="测试逐条审核门禁。",
                reviewed_conclusion_ids=[
                    fact["id"] for fact in row["candidate"].get("conclusions", [])
                ],
            )
            control_plane.resume_job(conn, job_id=job_id)

    def test_two_fact_models_and_one_prose_model_keep_their_audited_frontier(self):
        job, text, source_sha, chapter_model = self._history_job()
        models = _MultiModels()
        self.assertEqual(
            "needs_review",
            self._run_once(
                job, text, source_sha, chapter_model, narrative_model=models
            )[1],
        )
        self.assertEqual(2, len([call for call in models.calls if call[0] == "facts_generate"]))
        self.assertEqual(1, len([call for call in models.calls if call[0] == "facts_compare"]))
        self.assertFalse([call for call in models.calls if call[0] == "prose_generate"])
        with psycopg.connect(self.database_url) as conn:
            row = narrative_store.read_candidate(conn, job, "facts")
            self.assertEqual(2, row["review_payload"]["candidate_count"])
            self.assertEqual(1, len(row["review_payload"]["comparisons"]))
            outputs = narrative_store.read_outputs(conn, job_id=job)
            self.assertEqual(
                {"facts_generate", "facts_compare"},
                {
                    item["step"]
                    for item in outputs
                    if item["artifact_type"] == narrative_store.STEP_TYPE
                },
            )

        self._approve(job, "facts")
        self.assertEqual(
            "needs_review",
            self._run_once(
                job, text, source_sha, chapter_model, narrative_model=models
            )[1],
        )
        self.assertEqual(1, len([call for call in models.calls if call[0] == "prose_generate"]))
        self.assertFalse([call for call in models.calls if call[0] == "prose_compare"])

        self._approve(job, "prose")
        self.assertEqual(
            "completed",
            self._run_once(
                job, text, source_sha, chapter_model, narrative_model=models
            )[1],
        )
        self.assertEqual(2, len([call for call in models.calls if call[0] == "facts_generate"]))
        self.assertEqual(1, len([call for call in models.calls if call[0] == "prose_generate"]))


if __name__ == "__main__":
    unittest.main()
