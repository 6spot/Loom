"""PostgreSQL proof of the narrative generation/comparison/review graph."""
from __future__ import annotations

import copy
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
from psycopg.types.json import Jsonb

import control_plane
import narrative_acceptance
import narrative_store
import studio_jobs
from test_narrative_contract import drafts
from test_narrative_pipeline_postgres import NarrativeTestModel
import test_reading_pipeline_postgres as base
from common import sha256_json


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
            if self.owner.conflict and stage == "facts_compare":
                result["disagreements"] = [{
                    "id": "disagreement_001",
                    "conclusion_ids": ["f0"],
                    "message": "两个完整候选对同一来源事实给出不可自动消解的解释。",
                    "evidence": ["evidence_001"],
                }]
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

    def __init__(self, conflict=False):
        self.calls = []
        self.conflict = conflict
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

    def test_no_objection_frontier_auto_accepts_and_publishes(self):
        job, text, source_sha, chapter_model = self._history_job()
        models = _MultiModels()
        self.assertEqual(
            "completed",
            self._run_once(
                job, text, source_sha, chapter_model, narrative_model=models
            )[1],
        )
        self.assertEqual(2, len([call for call in models.calls if call[0] == "facts_generate"]))
        self.assertEqual(1, len([call for call in models.calls if call[0] == "facts_compare"]))
        self.assertEqual(1, len([call for call in models.calls if call[0] == "prose_generate"]))
        with psycopg.connect(self.database_url) as conn:
            facts = narrative_store.read_candidate(conn, job, "facts")
            prose = narrative_store.read_candidate(conn, job, "prose")
            self.assertEqual("accepted", facts["status"])
            self.assertIsNone(facts["review_id"])
            self.assertEqual("accepted", prose["status"])
            self.assertIsNone(prose["review_id"])
            self.assertEqual("policy_model_review", facts["acceptance_type"])
            self.assertEqual("policy_model_review", prose["acceptance_type"])
            self.assertEqual([], conn.execute(
                "SELECT review_id FROM chronicle.review_items"
                " WHERE job_id = %s AND payload->>'scope' = 'narrative'", (job,)
            ).fetchall())
            receipts = conn.execute(
                "SELECT acceptance_type, policy_version, review_id, model_output_sha256s,"
                " model_opinion_sha256s FROM chronicle.narrative_acceptances"
                " WHERE job_id = %s ORDER BY kind", (job,)
            ).fetchall()
            self.assertEqual(2, len(receipts))
            self.assertTrue(all(item[0] == "policy_model_review" for item in receipts))
            self.assertTrue(all(item[1] == "narrative-content-acceptance-v1" for item in receipts))
            self.assertTrue(all(item[2] is None for item in receipts))
            self.assertTrue(all(item[3] for item in receipts))
            self.assertTrue(receipts[0][4])
            outputs = narrative_store.read_outputs(conn, job_id=job)
            self.assertEqual(
                {"facts_generate", "facts_compare", "prose_generate"},
                {
                    item["step"]
                    for item in outputs
                    if item["artifact_type"] == narrative_store.STEP_TYPE
                },
            )
            publication = narrative_store.read_publication(conn)
            self.assertTrue(publication["paragraphs"])
            self.assertTrue(all(item["publication_id"] for item in publication["evidence"].values()))
            facts_acceptance, prose_acceptance = conn.execute(
                "SELECT facts_acceptance_id, prose_acceptance_id"
                " FROM chronicle.historical_narratives WHERE job_id = %s", (job,)
            ).fetchone()
            self.assertEqual(facts["acceptance_id"], str(facts_acceptance))
            self.assertEqual(prose["acceptance_id"], str(prose_acceptance))

    def test_source_conflict_stops_for_human_exception_then_publishes_one_bound_path(self):
        job, text, source_sha, chapter_model = self._history_job()
        models = _MultiModels(conflict=True)
        self.assertEqual(
            "needs_review",
            self._run_once(
                job, text, source_sha, chapter_model, narrative_model=models
            )[1],
        )
        with psycopg.connect(self.database_url) as conn:
            row = narrative_store.read_candidate(conn, job, "facts")
            self.assertEqual("open", row["status"])
            self.assertIsNone(row["acceptance_id"])
            self.assertEqual(0, conn.execute(
                "SELECT count(*) FROM chronicle.historical_narratives WHERE job_id = %s", (job,)
            ).fetchone()[0])
        self._approve(job, "facts")
        self.assertEqual(
            "completed",
            self._run_once(
                job, text, source_sha, chapter_model, narrative_model=models
            )[1],
        )
        self.assertEqual(2, len([call for call in models.calls if call[0] == "facts_generate"]))
        self.assertEqual(1, len([call for call in models.calls if call[0] == "prose_generate"]))
        with psycopg.connect(self.database_url) as conn:
            facts = narrative_store.read_candidate(conn, job, "facts")
            prose = narrative_store.read_candidate(conn, job, "prose")
            self.assertEqual("human", facts["acceptance_type"])
            self.assertIsNotNone(facts["review_id"])
            self.assertEqual("policy_model_review", prose["acceptance_type"])
            self.assertEqual(2, conn.execute(
                "SELECT count(*) FROM chronicle.narrative_acceptances WHERE job_id = %s", (job,)
            ).fetchone()[0])

    def test_postgres_publication_trigger_rejects_missing_or_wrong_acceptance(self):
        job, text, source_sha, chapter_model = self._history_job()
        models = _MultiModels()
        self.assertEqual(
            "completed",
            self._run_once(
                job, text, source_sha, chapter_model, narrative_model=models
            )[1],
        )
        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                "SELECT catalog_sha, facts_review_id, prose_review_id, facts_acceptance_id,"
                " prose_acceptance_id, facts_sha, prose_sha, payload"
                " FROM chronicle.historical_narratives WHERE job_id = %s", (job,)
            ).fetchone()
            catalog, facts_review, prose_review, facts_acceptance, prose_acceptance, facts_sha, prose_sha, payload = row
            args = ("f" * 64, job, catalog, facts_review, prose_review,
                    facts_acceptance, prose_acceptance, facts_sha, prose_sha, payload)
            with self.assertRaises(psycopg.Error):
                with conn.transaction():
                    conn.execute(
                        "INSERT INTO chronicle.historical_narratives"
                        " (version_sha, job_id, catalog_sha, facts_review_id, prose_review_id,"
                        " facts_acceptance_id, prose_acceptance_id, facts_sha, prose_sha, payload)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (*args[:3], facts_review, prose_review, None, None, facts_sha, prose_sha, payload),
                    )
            with self.assertRaises(psycopg.Error):
                with conn.transaction():
                    conn.execute(
                        "INSERT INTO chronicle.historical_narratives"
                        " (version_sha, job_id, catalog_sha, facts_review_id, prose_review_id,"
                        " facts_acceptance_id, prose_acceptance_id, facts_sha, prose_sha, payload)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        ("e" * 64, job, catalog, facts_review, prose_review,
                         facts_acceptance, prose_acceptance, "0" * 64, prose_sha, payload),
                    )

    def test_postgres_acceptance_trigger_rejects_forged_receipt_and_rolls_back(self):
        job, text, source_sha, chapter_model = self._history_job()
        models = _MultiModels()
        self.assertEqual(
            "completed",
            self._run_once(
                job, text, source_sha, chapter_model, narrative_model=models
            )[1],
        )
        with psycopg.connect(self.database_url) as conn:
            current = narrative_store.read_candidate(conn, job, "facts")
            old_receipt = current["acceptance"]
            forged_content = {"forged": True}
            parent_sha = current["candidate_sha"]
            revision_no = int(current["revision_no"] or 0) + 1

            def forged_candidate_sha(content):
                return sha256_json({
                    "job_id": str(job),
                    "kind": "facts",
                    "context": current["context"],
                    "candidate": content,
                    "parent_candidate_sha": parent_sha,
                    "revision_no": revision_no,
                    "upstream_candidate_sha": current["upstream_candidate_sha"],
                })

            def attempt(receipt, expected_error):
                candidate_sha = receipt["candidate_sha256"]
                with self.assertRaisesRegex(psycopg.Error, expected_error):
                    with conn.transaction():
                        conn.execute(
                            "INSERT INTO chronicle.narrative_candidate_versions"
                            " (candidate_sha, job_id, kind, review_id, parent_candidate_sha, revision_no,"
                            " upstream_candidate_sha, context_sha, context_payload, candidate_payload, model_version)"
                            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (
                                candidate_sha, job, "facts", None, parent_sha, revision_no,
                                current["upstream_candidate_sha"], current["context_sha"],
                                Jsonb(current["context"]),
                                Jsonb(forged_content), "direct-sql-forge",
                            ),
                        )
                        conn.execute(
                            "INSERT INTO chronicle.narrative_acceptances"
                            " (acceptance_id, job_id, kind, acceptance_type, policy_version,"
                            " input_sha256, candidate_sha256, draft_sha256, content_sha256,"
                            " pipeline_fingerprint, model_output_sha256s, model_opinion_sha256s,"
                            " decision, decision_reason, review_id, payload)"
                            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (
                                uuid.uuid4(), job, "facts", "policy_model_review",
                                receipt["policy_version"], receipt["input_sha256"],
                                receipt["candidate_sha256"], receipt["draft_sha256"],
                                receipt["content_sha256"], receipt["pipeline_fingerprint"],
                                receipt["model_output_sha256s"], receipt["model_opinion_sha256s"],
                                receipt["decision"], receipt["decision_reason"], None,
                                Jsonb(receipt),
                            ),
                        )
                self.assertEqual(
                    parent_sha,
                    narrative_store.read_candidate(conn, job, "facts")["candidate_sha"],
                )
                self.assertEqual(
                    0,
                    conn.execute(
                        "SELECT count(*) FROM chronicle.narrative_candidate_versions"
                        " WHERE job_id = %s AND candidate_sha = %s",
                        (job, candidate_sha),
                    ).fetchone()[0],
                )
                self.assertEqual(
                    0,
                    conn.execute(
                        "SELECT count(*) FROM chronicle.narrative_acceptances"
                        " WHERE job_id = %s AND candidate_sha256 = %s",
                        (job, candidate_sha),
                    ).fetchone()[0],
                )

            forged_sha = forged_candidate_sha(forged_content)
            stale_digest = copy.deepcopy(old_receipt)
            stale_digest.update({
                "candidate_sha256": forged_sha,
                "draft_sha256": sha256_json(forged_content),
                "content_sha256": sha256_json(forged_content),
            })
            attempt(stale_digest, "receipt digest")

            mismatched_content = narrative_acceptance.build_receipt(
                job_id=job,
                kind="facts",
                acceptance_type="policy_model_review",
                policy_version=old_receipt["policy_version"],
                input_sha256=old_receipt["input_sha256"],
                candidate_sha256=forged_sha,
                content=current["candidate"],
                pipeline_fingerprint=old_receipt["pipeline_fingerprint"],
                model_output_sha256s=old_receipt["model_output_sha256s"],
                model_opinion_sha256s=old_receipt["model_opinion_sha256s"],
                decision_reason=old_receipt["decision_reason"],
            )
            attempt(mismatched_content, "draft/content hash")

            reused_evidence = narrative_acceptance.build_receipt(
                job_id=job,
                kind="facts",
                acceptance_type="policy_model_review",
                policy_version=old_receipt["policy_version"],
                input_sha256=old_receipt["input_sha256"],
                candidate_sha256=forged_sha,
                content=forged_content,
                pipeline_fingerprint=old_receipt["pipeline_fingerprint"],
                model_output_sha256s=old_receipt["model_output_sha256s"],
                model_opinion_sha256s=old_receipt["model_opinion_sha256s"],
                decision_reason=old_receipt["decision_reason"],
            )
            attempt(reused_evidence, "do not produce the current candidate payload")

    def test_human_revision_is_a_new_frontier_and_invalidates_old_acceptance(self):
        job, text, source_sha, chapter_model = self._history_job()
        models = _MultiModels(conflict=True)
        self.assertEqual(
            "needs_review",
            self._run_once(
                job, text, source_sha, chapter_model, narrative_model=models
            )[1],
        )
        self._approve(job, "facts")
        with psycopg.connect(self.database_url) as conn:
            old = narrative_store.read_candidate(conn, job, "facts")
            old_acceptance_id = old["acceptance_id"]
            edited = copy.deepcopy(old["candidate"])
            edited["title"] = "人工修订后的综合叙事"
            revised = narrative_store.revise_candidate(
                conn, job_id=job, kind="facts", candidate_sha=old["candidate_sha"],
                content=edited, rationale="人工编辑必须重新核对完整稿。",
            )
            self.assertEqual("open", revised["status"])
            self.assertEqual(1, revised["revision_no"])
            self.assertEqual(old["candidate_sha"], revised["parent_candidate_sha"])
            self.assertNotEqual(old["candidate_sha"], revised["candidate_sha"])
            self.assertNotEqual(old_acceptance_id, revised["acceptance_id"])
            self.assertIsNone(revised["decision"])
            self.assertEqual("needs_review", control_plane.get_job_detail(conn, job_id=job)["status"])
            self.assertEqual("resolved", conn.execute(
                "SELECT status FROM chronicle.review_items WHERE review_id = %s",
                (old["review_id"],),
            ).fetchone()[0])
            stale_review_receipt = narrative_acceptance.build_receipt(
                job_id=job,
                kind="facts",
                acceptance_type="human",
                policy_version=old["acceptance"]["policy_version"],
                input_sha256=revised["context_sha"],
                candidate_sha256=revised["candidate_sha"],
                content=revised["candidate"],
                pipeline_fingerprint=old["acceptance"]["pipeline_fingerprint"],
                model_output_sha256s=old["acceptance"]["model_output_sha256s"],
                model_opinion_sha256s=old["acceptance"]["model_opinion_sha256s"],
                decision_reason=old["acceptance"]["decision_reason"],
                review_id=old["review_id"],
            )
            with self.assertRaisesRegex(psycopg.Error, "candidate revision review"):
                with conn.transaction():
                    conn.execute(
                        "INSERT INTO chronicle.narrative_acceptances"
                        " (acceptance_id, job_id, kind, acceptance_type, policy_version,"
                        " input_sha256, candidate_sha256, draft_sha256, content_sha256,"
                        " pipeline_fingerprint, model_output_sha256s, model_opinion_sha256s,"
                        " decision, decision_reason, review_id, payload)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            uuid.uuid4(), job, "facts", "human",
                            stale_review_receipt["policy_version"], stale_review_receipt["input_sha256"],
                            stale_review_receipt["candidate_sha256"], stale_review_receipt["draft_sha256"],
                            stale_review_receipt["content_sha256"], stale_review_receipt["pipeline_fingerprint"],
                            stale_review_receipt["model_output_sha256s"], stale_review_receipt["model_opinion_sha256s"],
                            stale_review_receipt["decision"], stale_review_receipt["decision_reason"],
                            old["review_id"], Jsonb(stale_review_receipt),
                        ),
                    )
            self.assertIsNone(narrative_store.read_candidate(conn, job, "facts")["acceptance_id"])
        self._approve(job, "facts")
        self.assertEqual(
            "completed",
            self._run_once(
                job, text, source_sha, chapter_model, narrative_model=models
            )[1],
        )
        with psycopg.connect(self.database_url) as conn:
            facts = narrative_store.read_candidate(conn, job, "facts")
            prose = narrative_store.read_candidate(conn, job, "prose")
            self.assertEqual("human", facts["acceptance_type"])
            self.assertNotEqual(old_acceptance_id, facts["acceptance_id"])
            self.assertEqual(facts["candidate_sha"], prose["upstream_candidate_sha"])
            published_facts, published_prose = conn.execute(
                "SELECT facts_acceptance_id, prose_acceptance_id"
                " FROM chronicle.historical_narratives WHERE job_id = %s", (job,)
            ).fetchone()
            self.assertEqual(facts["acceptance_id"], str(published_facts))
            self.assertEqual(prose["acceptance_id"], str(published_prose))


if __name__ == "__main__":
    unittest.main()
