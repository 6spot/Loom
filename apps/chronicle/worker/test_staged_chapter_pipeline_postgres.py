"""Real PostgreSQL/Runner coverage for 0.4 staged chapter production.

Only model completions are fixtures. All prompts, durable steps, resumes,
human decisions, acceptance, assembly and publication use production paths.
"""
from __future__ import annotations

import copy
import json
import sys
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import psycopg

HERE = Path(__file__).resolve().parent
for path in (str(HERE), str(HERE.parent / "persistence")):
    if path not in sys.path:
        sys.path.insert(0, path)

import chapter_content_review as content_review
import chapter_contract
import chapter_production as protocol
import chapter_production_store as store
import chapter_stage as stage
import chapter_store
import control_plane
import ingestion_worker as worker
import staged_chapter
from common import PersistenceConflict, sha256_json
import test_chapter_pipeline_postgres as legacy
import test_person_state_pipeline_postgres as state_pipeline
from staged_pipeline_fixture import CORRECT_FIRST, TEXT, WRONG_FIRST, ScriptedModels

WORKER = "staged-pipeline-test"
LIMITS = chapter_contract.ChapterLimits()


class InvalidExtractionModels(ScriptedModels):
    """A complete historical extraction with a controlled structural error."""
    def __init__(self, *, invalid_attempts, failures=None):
        super().__init__(failures=failures)
        self.invalid_attempts = invalid_attempts
        self.extraction_prompts = []
        self.extraction_raw = []

    def complete(self, expected_step, slot, prompt):
        raw = super().complete(expected_step, slot, prompt)
        if expected_step == "extraction":
            self.extraction_prompts.append(prompt)
            if self.count(expected_step, slot) in self.invalid_attempts:
                value = json.loads(raw)
                value["bundle"]["entities"][0]["kind"] = "person"
                raw = json.dumps(value, ensure_ascii=False)
            self.extraction_raw.append(raw)
        return raw


class StagedChapterPipelinePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control_url = legacy._control_url()

    setUp = legacy.ChapterPipelinePostgresTests.setUp
    tearDown = legacy.ChapterPipelinePostgresTests.tearDown
    _queue_job = legacy.ChapterPipelinePostgresTests._queue_job
    _job_status = legacy.ChapterPipelinePostgresTests._job_status
    _person_state_plan = state_pipeline.PersonStatePipelineTests._person_state_plan
    _open_person_state_reviews = state_pipeline.PersonStatePipelineTests._open_person_state_reviews
    _approve_person_state = state_pipeline.PersonStatePipelineTests._approve_person_state

    def _prepared_extract(self, *, limits=LIMITS):
        job_id, revision_id, source_sha = self._queue_job(TEXT)
        with psycopg.connect(self.database_url) as conn:
            control_plane.claim_job(conn, worker=WORKER, lease_seconds=300, job_id=job_id)
        _, _, plan, requests = stage.load_chapter_inputs(
            self.database_url, job_id=job_id, revision_source=lambda _job: (TEXT, source_sha),
            limits=limits, candidate_version="0.4",
        )
        self.assertEqual(len(requests), 1)
        with psycopg.connect(self.database_url) as conn:
            stage.ensure_chapter_topology(conn, job_id=job_id, worker=WORKER, plan=plan, text=TEXT)
            chunk_id = conn.execute("SELECT chunk_id FROM chronicle.ingestion_chunks WHERE job_id = %s", (job_id,)).fetchone()[0]
        return {"job_id": job_id, "revision_id": revision_id, "source_sha": source_sha,
                "chunk_id": chunk_id, "plan": plan, "requests": requests}

    def _extract(self, ctx, script, *, limits=LIMITS):
        return stage.execute_chapter_extract(
            self.database_url, job_id=ctx["job_id"], worker=WORKER, plan=ctx["plan"],
            requests=ctx["requests"], model=script.models, limits=limits, lease_seconds=300,
        )

    def _run_job(self, job_id, source_sha, script):
        result = worker.run_once(
            self.database_url, worker=WORKER, revision_source=lambda _job: (TEXT, source_sha),
            chapter_model=script.models, chapter_limits=LIMITS, job_id=job_id, lease_seconds=300,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result[0], job_id)
        return result[1]

    def _records(self, ctx):
        with psycopg.connect(self.database_url) as conn:
            return store.read_outputs(conn, job_id=ctx["job_id"], chunk_id=ctx["chunk_id"])

    def _accepted(self, ctx):
        with psycopg.connect(self.database_url) as conn:
            return chapter_store.read_accepted_chapters(conn, job_id=ctx["job_id"])

    def _counts(self, ctx):
        with psycopg.connect(self.database_url) as conn:
            runs = conn.execute("SELECT count(*) FROM chronicle.ingestion_chunk_runs WHERE chunk_id = %s", (ctx["chunk_id"],)).fetchone()[0]
            reviews = conn.execute("SELECT count(*) FROM chronicle.review_items WHERE job_id = %s", (ctx["job_id"],)).fetchone()[0]
            published = conn.execute("SELECT count(*) FROM chronicle.chapter_publications WHERE job_id = %s", (ctx["job_id"],)).fetchone()[0]
        return {"runs": runs, "reviews": reviews, "published": published}

    def _assert_initial_steps_once(self, script):
        self.assertEqual(script.count("translation"), 1)
        self.assertEqual(script.count("extraction"), 1)
        self.assertEqual(script.count("comparison"), 0)

    def _assert_repaired(self, ctx, script):
        self._assert_initial_steps_once(script)
        accepted = self._accepted(ctx)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["artifact"]["candidate"]["translation"]["blocks"][0]["text"], CORRECT_FIRST)
        drafts = [record for record in self._records(ctx) if record["artifact_type"] == store.DRAFT_TYPE]
        self.assertEqual([record["round"] for record in drafts], [0, 1])
        self.assertEqual(drafts[0]["candidate"]["translation"]["blocks"][0]["text"], WRONG_FIRST)
        self.assertEqual(drafts[1]["parent_sha256"], drafts[0]["output_sha256"])
        final_review = [entry for entry in script.inputs if entry["step"] == "review"][-1]["data"]
        self.assertTrue(final_review["previous_issues"])
        self.assertTrue(any(entry["step"] == "review" for entry in final_review["history"]))
        historical_drafts = [entry for entry in final_review["history"] if entry["artifact_type"] == store.DRAFT_TYPE]
        self.assertTrue(any(entry["candidate"] == drafts[0]["candidate"] for entry in historical_drafts))
        self.assertEqual(len(final_review["candidate"]["translation"]["blocks"]), 3)

    def test_actual_prompts_keep_full_context_and_accept_separate_results(self):
        ctx = self._prepared_extract()
        script = ScriptedModels(parallel_barrier=True)
        self.assertEqual(self._extract(ctx, script), "ok")
        self._assert_initial_steps_once(script)
        self.assertEqual(script.count("linking"), 1)
        self.assertEqual(script.count("review"), 1)
        self.assertEqual(script.count("repair"), 0)
        records = self._records(ctx)
        results = [record for record in records if record["artifact_type"] == store.STEP_TYPE]
        self.assertEqual({record["step"] for record in results}, {"translation", "extraction", "linking", "review"})
        translated = next(record for record in results if record["step"] == "translation")
        extracted = next(record for record in results if record["step"] == "extraction")
        self.assertTrue(translated["raw_text"].startswith(CORRECT_FIRST))
        self.assertNotIn("裴松之注", translated["raw_text"])
        self.assertNotIn("translation", extracted["parsed"])
        self.assertNotIn("unit_phases", extracted["parsed"]["person_states"])
        self.assertTrue(all(entry["source"]["normalized_text"] == TEXT for entry in script.inputs))
        self.assertTrue(all(entry["data"] == {} for entry in script.inputs if entry["step"] in ("translation", "extraction")))
        accepted = self._accepted(ctx)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["artifact"]["version"], "0.4")
        self.assertEqual(accepted[0]["artifact"]["production_receipt"]["candidate_sha256"], next(record["candidate_sha256"] for record in records if record["artifact_type"] == store.DRAFT_TYPE))
        self.assertEqual(self._counts(ctx), {"runs": 1, "reviews": 0, "published": 0})

    def test_all_chapters_in_one_job_share_frozen_model_and_step_policy(self):
        text = legacy.TEXT_DISTINCT
        job_id, _revision, source_sha = self._queue_job(text)
        with psycopg.connect(self.database_url) as conn:
            control_plane.claim_job(conn, worker=WORKER, lease_seconds=300, job_id=job_id)
        _, _, plan, requests = stage.load_chapter_inputs(
            self.database_url, job_id=job_id, revision_source=lambda _job: (text, source_sha),
            limits=LIMITS, candidate_version="0.4",
        )
        self.assertEqual(len(requests), 2)
        config = ScriptedModels().models.public_config()
        with psycopg.connect(self.database_url) as conn:
            stage.ensure_chapter_topology(conn, job_id=job_id, worker=WORKER, plan=plan, text=text)
            chunks = conn.execute(
                "SELECT chunk_id FROM chronicle.ingestion_chunks WHERE job_id = %s ORDER BY chunk_index",
                (job_id,),
            ).fetchall()
            store.freeze_pipeline(conn, job_id=job_id, chunk_id=chunks[0][0], worker=WORKER,
                                  request=requests[0], config=config)
            for drift in ("model", "steps", "budget", "prompt"):
                with self.subTest(drift=drift):
                    changed = copy.deepcopy(config)
                    if drift == "model":
                        changed["models"]["executor"]["model"] = "another-model"
                    elif drift == "steps":
                        changed["steps"]["translation"] = ["reviewer_0"]
                    elif drift == "budget":
                        changed["max_step_attempts"] += 1
                    else:
                        changed["prompt_templates"]["extraction"] = sha256_json("changed extraction instructions")
                    with self.assertRaisesRegex(PersistenceConflict, "frozen for the whole job"):
                        store.freeze_pipeline(conn, job_id=job_id, chunk_id=chunks[1][0], worker=WORKER,
                                              request=requests[1], config=changed)
                    self.assertEqual(store.read_outputs(conn, job_id=job_id, chunk_id=chunks[1][0]), [])
            second = store.freeze_pipeline(conn, job_id=job_id, chunk_id=chunks[1][0], worker=WORKER,
                                           request=requests[1], config=config)
            self.assertEqual(second["config"], config)
        # A different job may explicitly choose another configuration.
        other = self._prepared_extract()
        with psycopg.connect(self.database_url) as conn:
            independent = store.freeze_pipeline(conn, job_id=other["job_id"], chunk_id=other["chunk_id"],
                worker=WORKER, request=other["requests"][0], config=changed)
            self.assertEqual(independent["config"], changed)

    def test_invalid_extraction_retries_same_node_with_full_feedback_without_retranslation(self):
        ctx = self._prepared_extract()
        script = InvalidExtractionModels(invalid_attempts={1})
        self.assertEqual(self._extract(ctx, script), "ok")
        self.assertEqual(script.count("translation"), 1)
        self.assertEqual(script.count("extraction"), 2)
        self.assertEqual(script.count("linking"), 1)
        self.assertEqual(script.count("review"), 1)
        self.assertEqual(script.count("comparison"), 0)
        records = self._records(ctx)
        attempts = [r for r in records if r["artifact_type"] == store.ATTEMPT_TYPE and r["step"] == "extraction"]
        results = [r for r in records if r["artifact_type"] == store.STEP_TYPE and r["step"] == "extraction"]
        self.assertEqual([r["attempt"] for r in attempts], [1, 2])
        self.assertEqual([r["status"] for r in results], ["invalid", "completed"])
        self.assertEqual(len({r["node_key"] for r in attempts + results}), 1)
        self.assertEqual([r["raw_text"] for r in results], script.extraction_raw)
        self.assertEqual([r["prompt"] for r in attempts], script.extraction_prompts)
        self.assertEqual({r["base_prompt_sha256"] for r in attempts}, {sha256_json(attempts[0]["prompt"])})
        self.assertIsNone(attempts[0]["retry_of"])
        self.assertEqual(attempts[1]["retry_of"], results[0]["output_sha256"])
        feedback = json.loads(next(line.removeprefix("PREVIOUS_ATTEMPT=") for line in attempts[1]["prompt"].splitlines()
                                   if line.startswith("PREVIOUS_ATTEMPT=")))
        self.assertEqual(feedback, {key: results[0][key] for key in ("output_sha256", "raw_text", "validation_errors")})
        self.assertTrue(any("/bundle/entities/0/kind" in error for error in feedback["validation_errors"]))
        reviewed_history = [entry for entry in script.inputs if entry["step"] == "review"][0]["data"]["history"]
        self.assertTrue(any(entry.get("output_sha256") == results[0]["output_sha256"] for entry in reviewed_history))
        self.assertEqual(len(self._accepted(ctx)), 1)
        self.assertEqual(self._counts(ctx), {"runs": 1, "reviews": 0, "published": 0})

    def test_invalid_extraction_exhausts_saved_budget_and_resume_never_opens_another_node(self):
        ctx = self._prepared_extract()
        script = InvalidExtractionModels(invalid_attempts={1, 2})
        self.assertEqual(self._extract(ctx, script), "failed")
        self.assertEqual(script.count("extraction"), 2)
        records = self._records(ctx)
        script.deny_calls = True
        self.assertEqual(self._extract(ctx, script), "failed")
        self.assertEqual(self._records(ctx), records)
        self.assertEqual(script.count("extraction"), 2)
        self.assertEqual(script.count("translation"), 1)
        self.assertEqual(script.count("linking"), 0)
        self.assertEqual(script.count("review"), 0)
        attempts = [r for r in records if r["artifact_type"] == store.ATTEMPT_TYPE and r["step"] == "extraction"]
        results = [r for r in records if r["artifact_type"] == store.STEP_TYPE and r["step"] == "extraction"]
        self.assertEqual(len(attempts), 2)
        self.assertEqual(len(results), 2)
        self.assertEqual(len({r["node_key"] for r in attempts + results}), 1)
        self.assertTrue(all(r["status"] == "invalid" for r in results))
        self.assertFalse(any(r["artifact_type"] == store.ACCEPTANCE_TYPE for r in records))
        self.assertEqual(self._accepted(ctx), [])
        self.assertEqual(self._counts(ctx), {"runs": 2, "reviews": 0, "published": 0})

    def test_transport_failure_during_correction_retains_invalid_feedback_on_resume(self):
        ctx = self._prepared_extract()
        script = InvalidExtractionModels(invalid_attempts={1}, failures={("extraction", "executor"): {2}})
        script.models = replace(script.models, max_step_attempts=3)
        self.assertEqual(self._extract(ctx, script), "failed")
        self.assertEqual(script.count("extraction"), 2)
        self.assertEqual(self._extract(ctx, script), "ok")
        self.assertEqual(script.count("translation"), 1)
        self.assertEqual(script.count("extraction"), 3)
        records = self._records(ctx)
        attempts = [r for r in records if r["artifact_type"] == store.ATTEMPT_TYPE and r["step"] == "extraction"]
        results = [r for r in records if r["artifact_type"] == store.STEP_TYPE and r["step"] == "extraction"]
        self.assertEqual([r["status"] for r in results], ["invalid", "failed", "completed"])
        self.assertEqual([r["attempt"] for r in attempts], [1, 2, 3])
        self.assertEqual(len({r["node_key"] for r in attempts + results}), 1)
        self.assertEqual(attempts[1]["prompt"], attempts[2]["prompt"])
        self.assertEqual(attempts[1]["retry_of"], results[0]["output_sha256"])
        self.assertEqual(attempts[2]["retry_of"], results[0]["output_sha256"])
        self.assertIn("PREVIOUS_ATTEMPT=", attempts[2]["prompt"])
        self.assertEqual(len(self._accepted(ctx)), 1)

    def test_oversized_retry_context_stops_locally_and_still_saves_pending_translation(self):
        limits = replace(LIMITS, max_prompt_chars=20000)
        ctx = self._prepared_extract(limits=limits)
        release_translation = threading.Event()
        original_retry = protocol.retry_prompt

        class PendingTranslation(InvalidExtractionModels):
            def complete(self, expected_step, slot, prompt):
                if expected_step == "translation" and not release_translation.wait(timeout=15):
                    raise AssertionError("translation was not released after the local retry limit")
                return super().complete(expected_step, slot, prompt)

        def observe_retry_limit(*args, **kwargs):
            try:
                return original_retry(*args, **kwargs)
            except protocol.RetryPromptLimitExceeded:
                release_translation.set()
                raise

        script = PendingTranslation(invalid_attempts={1})
        try:
            with mock.patch.object(protocol, "retry_prompt", side_effect=observe_retry_limit):
                self.assertEqual(self._extract(ctx, script, limits=limits), "failed")
        finally:
            release_translation.set()
        records = self._records(ctx)
        translation = [r for r in records if r["artifact_type"] == store.STEP_TYPE and r["step"] == "translation"]
        extraction = [r for r in records if r["artifact_type"] == store.STEP_TYPE and r["step"] == "extraction"]
        self.assertEqual([r["status"] for r in translation], ["completed"])
        self.assertEqual([r["status"] for r in extraction], ["invalid"])
        self.assertEqual(extraction[0]["raw_text"], script.extraction_raw[0])
        script.deny_calls = True
        self.assertEqual(self._extract(ctx, script, limits=limits), "failed")
        self.assertEqual(self._records(ctx), records)
        self.assertEqual(script.count("translation"), 1)
        self.assertEqual(script.count("extraction"), 1)
        self.assertEqual(self._accepted(ctx), [])
        self.assertEqual(self._counts(ctx), {"runs": 2, "reviews": 0, "published": 0})
        with psycopg.connect(self.database_url) as conn:
            errors = conn.execute("SELECT error FROM chronicle.ingestion_chunk_runs WHERE chunk_id = %s", (ctx["chunk_id"],)).fetchall()
        self.assertTrue(all("complete-context prompt limit" in row[0] for row in errors))

    def test_invalid_review_cannot_drop_its_objection_in_a_format_retry(self):
        class InvalidOpinion(ScriptedModels):
            def complete(self, expected_step, slot, prompt):
                raw = super().complete(expected_step, slot, prompt)
                if expected_step == "review" and self.count("review") == 1:
                    report = json.loads(raw)
                    report["verdict"] = "needs_review"
                    del report["coverage"]
                    return json.dumps(report, ensure_ascii=False)
                # A second call would silently drop the first objection.
                if expected_step == "review":
                    report = json.loads(raw)
                    report.update(verdict="pass", issues=[], dispositions=[])
                    return json.dumps(report, ensure_ascii=False)
                return raw

        ctx = self._prepared_extract()
        script = InvalidOpinion(mode="revise")
        self.assertEqual(self._extract(ctx, script), "needs_review")
        self.assertEqual(script.count("review"), 1)
        records = self._records(ctx)
        reports = [r for r in records if r["artifact_type"] == store.STEP_TYPE and r["step"] == "review"]
        self.assertEqual([r["status"] for r in reports], ["invalid"])
        self.assertEqual(self._accepted(ctx), [])
        with psycopg.connect(self.database_url) as conn:
            review_id = conn.execute("SELECT review_id FROM chronicle.review_items WHERE job_id=%s", (ctx["job_id"],)).fetchone()[0]
            packet = content_review.read_content_review(conn, review_id)["packet"]
        self.assertTrue(any(issue.get("model_issue_id") == "subject-assignment" for issue in packet["issues"]))
        self.assertEqual(packet["candidate"]["translation"]["blocks"][0]["text"], WRONG_FIRST)
        self.assertIn(reports[0]["output_sha256"], packet["step_output_sha256s"])
        # Reusing an invalid opinion must precede even the one-attempt budget
        # check; otherwise a later sibling failure could block this gate.
        plan = next(r for r in records if r["artifact_type"] == store.PLAN_TYPE)
        attempt = next(r for r in records if r["artifact_type"] == store.ATTEMPT_TYPE and r["step"] == "review")
        with psycopg.connect(self.database_url) as conn:
            resumed, reused = store.begin_attempt(conn, job_id=ctx["job_id"], chunk_id=ctx["chunk_id"],
                worker=WORKER, plan=plan, step="review", round=attempt["round"], slot=attempt["slot"],
                data=attempt["input"], prompt=attempt["prompt"], model_config=attempt["model_config"], max_attempts=1)
        self.assertTrue(reused)
        self.assertEqual(resumed["output_sha256"], reports[0]["output_sha256"])
        script.deny_calls = True
        self.assertEqual(self._extract(ctx, script), "needs_review")
        self.assertEqual(script.count("review"), 1)
        self.assertEqual(self._counts(ctx), {"runs": 0, "reviews": 1, "published": 0})

    def test_extraction_transport_retry_reuses_completed_translation(self):
        ctx = self._prepared_extract()
        script = ScriptedModels(failures={("extraction", "executor"): {1}})
        self.assertEqual(self._extract(ctx, script), "failed")
        self.assertEqual(self._accepted(ctx), [])
        failed = [record for record in self._records(ctx) if record["artifact_type"] == store.STEP_TYPE and record["status"] == "failed"]
        self.assertEqual([record["step"] for record in failed], ["extraction"])
        self.assertEqual(failed[0]["raw_text"], "{\"partial\":")
        self.assertIsNone(failed[0]["receipt"]["usage"])
        self.assertEqual(self._extract(ctx, script), "ok")
        self.assertEqual(script.count("translation"), 1)
        self.assertEqual(script.count("extraction"), 2)
        self.assertEqual(script.count("linking"), 1)
        self.assertEqual(script.count("review"), 1)
        self.assertEqual(self._counts(ctx)["runs"], 2)

    def test_missing_reviewer_blocks_acceptance_and_only_that_slot_retries(self):
        ctx = self._prepared_extract()
        script = ScriptedModels(reviewers=2, failures={("review", "reviewer_1"): {1}})
        self.assertEqual(self._extract(ctx, script), "failed")
        self.assertEqual(self._accepted(ctx), [])
        self.assertFalse(any(record["artifact_type"] == store.ACCEPTANCE_TYPE for record in self._records(ctx)))
        self.assertEqual(self._extract(ctx, script), "ok")
        self._assert_initial_steps_once(script)
        self.assertEqual(script.count("linking"), 1)
        self.assertEqual(script.count("review", "reviewer_0"), 1)
        self.assertEqual(script.count("review", "reviewer_1"), 2)
        reports = [record for record in self._records(ctx) if record["artifact_type"] == store.STEP_TYPE and record["step"] == "review"]
        self.assertEqual(sorted(record["status"] for record in reports), ["completed", "completed", "failed"])
        receipt = self._accepted(ctx)[0]["artifact"]["production_receipt"]
        self.assertEqual(len(receipt["decision"]["review_output_sha256s"]), 2)

    def test_failed_repair_resumes_reserved_round_without_repeating_review(self):
        ctx = self._prepared_extract()
        script = ScriptedModels(mode="revise", failures={("repair", "executor"): {1}})
        self.assertEqual(self._extract(ctx, script), "failed")
        self.assertEqual(script.count("review"), 1)
        self.assertEqual(self._extract(ctx, script), "ok")
        self._assert_repaired(ctx, script)
        self.assertEqual(script.count("repair"), 2)
        self.assertEqual(script.count("linking"), 2)
        self.assertEqual(script.count("review"), 2)
        self.assertEqual(self._counts(ctx)["reviews"], 0)
        history = [entry for entry in script.inputs if entry["step"] == "review"][-1]["data"]["history"]
        self.assertTrue(any(entry["step"] == "repair" and entry["status"] == "failed" for entry in history))

    def test_completed_repair_survives_relink_failure_without_new_repair(self):
        ctx = self._prepared_extract()
        script = ScriptedModels(mode="revise", failures={("linking", "executor"): {2}})
        self.assertEqual(self._extract(ctx, script), "failed")
        self.assertEqual(script.count("repair"), 1)
        self.assertEqual(script.count("review"), 1)
        self.assertEqual(self._extract(ctx, script), "ok")
        self._assert_repaired(ctx, script)
        self.assertEqual(script.count("repair"), 1)
        self.assertEqual(script.count("linking"), 3)
        self.assertEqual(script.count("review"), 2)
        self.assertEqual(self._counts(ctx)["reviews"], 0)
        history = [entry for entry in script.inputs if entry["step"] == "review"][-1]["data"]["history"]
        self.assertTrue(any(entry["step"] == "linking" and entry["status"] == "failed" for entry in history))

    def test_final_review_failure_reuses_repaired_draft_and_links(self):
        ctx = self._prepared_extract()
        script = ScriptedModels(mode="revise", failures={("review", "reviewer_0"): {2}})
        self.assertEqual(self._extract(ctx, script), "failed")
        self.assertEqual(self._extract(ctx, script), "ok")
        self._assert_repaired(ctx, script)
        self.assertEqual(script.count("repair"), 1)
        self.assertEqual(script.count("linking"), 2)
        self.assertEqual(script.count("review"), 3)

    def test_saved_acceptance_is_adopted_after_artifact_transaction_crash(self):
        ctx = self._prepared_extract()
        script = ScriptedModels()
        with mock.patch.object(chapter_store, "record_accepted_chapter_fenced", side_effect=RuntimeError("test crash before artifact")):
            with self.assertRaisesRegex(RuntimeError, "test crash before artifact"):
                self._extract(ctx, script)
        self.assertEqual(self._accepted(ctx), [])
        self.assertEqual(self._counts(ctx)["runs"], 0)
        self.assertEqual(sum(record["artifact_type"] == store.ACCEPTANCE_TYPE for record in self._records(ctx)), 1)
        original_calls = copy.deepcopy(script.calls)
        script.deny_calls = True
        self.assertEqual(self._extract(ctx, script), "ok")
        self.assertEqual(self._extract(ctx, script), "ok")
        self.assertEqual(script.calls, original_calls)
        self.assertEqual(len(self._accepted(ctx)), 1)
        self.assertEqual(self._counts(ctx), {"runs": 1, "reviews": 0, "published": 0})

    def _content_gate(self, mode):
        job_id, revision_id, source_sha = self._queue_job(TEXT)
        script = ScriptedModels(mode=mode)
        self.assertEqual(self._run_job(job_id, source_sha, script), "needs_review", self._job_status(job_id))
        with psycopg.connect(self.database_url) as conn:
            rows = conn.execute("SELECT review_id, kind, payload FROM chronicle.review_items WHERE job_id = %s", (job_id,)).fetchall()
            self.assertEqual(len(rows), 1)
            review_id, kind, header = rows[0]
            self.assertEqual(kind, "stage_gate")
            self.assertEqual(header["scope"], "chapter_content")
            self.assertEqual(conn.execute("SELECT stage FROM chronicle.ingestion_job_stages WHERE job_id = %s AND status = 'needs_review'", (job_id,)).fetchone()[0], "extract")
            packet = content_review.read_content_review(conn, review_id)["packet"]
            self.assertEqual(conn.execute("SELECT count(*) FROM chronicle.ingestion_chunk_runs r JOIN chronicle.ingestion_chunks c USING (chunk_id) WHERE c.job_id = %s", (job_id,)).fetchone()[0], 0)
        return job_id, revision_id, source_sha, script, review_id, packet

    def _decide_content(self, job_id, review_id, packet, *, decision, replacement=CORRECT_FIRST):
        value = {"decision": decision, "plan_fingerprint": packet["plan_fingerprint"],
                 "candidate_sha256": packet["candidate_sha256"], "history_sha256": packet["history_sha256"],
                 "rationale": "测试操作员核对完整原文及全部历史结果。",
                 "issue_dispositions": [{"issue_id": issue["id"], "disposition": "resolved" if decision == "revise" else "rejected",
                                         "rationale": "根据策授瑜核对当前稿的任命关系。"} for issue in packet["issues"]]}
        if decision == "revise":
            value["patches"] = [{"op": "replace", "path": "/translation/blocks/0/text",
                                 "before_sha256": sha256_json(packet["candidate"]["translation"]["blocks"][0]["text"]),
                                 "value": replacement}]
        with psycopg.connect(self.database_url) as conn:
            content_review.resolve_content_review(conn, review_id=review_id, decision=value)
            control_plane.resume_job(conn, job_id=job_id)

    def _assert_state_gate_without_chunk_failure(self, job_id):
        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM chronicle.review_items WHERE job_id = %s AND kind = 'chunk_failure'", (job_id,)).fetchone()[0], 0)
            open_scopes = conn.execute("SELECT payload->>'scope' FROM chronicle.review_items WHERE job_id = %s AND status = 'open'", (job_id,)).fetchall()
            self.assertTrue(open_scopes)
            self.assertEqual({row[0] for row in open_scopes}, {"person_state"})
            accepted = chapter_store.read_accepted_chapters(conn, job_id=job_id)
            self.assertEqual(len(accepted), 1)
            self.assertEqual(accepted[0]["artifact"]["version"], "0.4")
            self.assertEqual(conn.execute("SELECT count(*) FROM chronicle.chapter_publications WHERE job_id = %s", (job_id,)).fetchone()[0], 0)
        return accepted[0]["artifact"]

    def test_worker_human_accept_resumes_without_models_or_chunk_failure(self):
        job_id, _revision, source_sha, script, review_id, packet = self._content_gate("gate")
        calls = copy.deepcopy(script.calls)
        self._decide_content(job_id, review_id, packet, decision="accept")
        script.deny_calls = True
        self.assertEqual(self._run_job(job_id, source_sha, script), "needs_review", self._job_status(job_id))
        artifact = self._assert_state_gate_without_chunk_failure(job_id)
        self.assertEqual(script.calls, calls)
        self.assertEqual(artifact["production_receipt"]["decision"]["kind"], "human")
        self.assertEqual(artifact["production_receipt"]["candidate_sha256"], packet["candidate_sha256"])

    def test_returning_to_earlier_text_does_not_replay_its_old_human_decision(self):
        job_id, _revision, source_sha, script, first_id, first = self._content_gate("gate")
        self._decide_content(job_id, first_id, first, decision="revise", replacement=WRONG_FIRST)
        self.assertEqual(self._run_job(job_id, source_sha, script), "needs_review")
        with psycopg.connect(self.database_url) as conn:
            second_id = conn.execute(
                "SELECT review_id FROM chronicle.review_items WHERE job_id = %s"
                " AND status = 'open' AND payload->>'scope' = 'chapter_content'", (job_id,),
            ).fetchone()[0]
            second = content_review.read_content_review(conn, second_id)["packet"]
        self._decide_content(job_id, second_id, second, decision="revise", replacement=CORRECT_FIRST)
        original = staged_chapter.Runner._revised_draft
        revisions = []

        def at_most_one_revision(runner, draft, *args, **kwargs):
            revisions.append(draft["output_sha256"])
            if len(revisions) > 1:
                raise AssertionError("old human decision was replayed on a different draft")
            return original(runner, draft, *args, **kwargs)

        with mock.patch.object(staged_chapter.Runner, "_revised_draft", autospec=True,
                               side_effect=at_most_one_revision):
            self.assertEqual(self._run_job(job_id, source_sha, script), "needs_review")
        self.assertEqual(len(revisions), 1)
        with psycopg.connect(self.database_url) as conn:
            rows = conn.execute(
                "SELECT review_id FROM chronicle.review_items WHERE job_id = %s"
                " AND status = 'open' AND payload->>'scope' = 'chapter_content'", (job_id,),
            ).fetchall()
            self.assertEqual(len(rows), 1)
            third_id = rows[0][0]
            third = content_review.read_content_review(conn, third_id)["packet"]
            records = store.read_outputs(conn, job_id=job_id, chunk_id=third["chunk_id"])
            self.assertEqual(chapter_store.read_accepted_chapters(conn, job_id=job_id), [])
        self.assertNotIn(third_id, (first_id, second_id))
        self.assertEqual(third["candidate_sha256"], first["candidate_sha256"])
        self.assertNotEqual(third["history_sha256"], first["history_sha256"])
        self.assertEqual(third["history"][:len(second["history"])], second["history"])
        drafts = [record for record in records if record["artifact_type"] == store.DRAFT_TYPE]
        self.assertEqual([draft["round"] for draft in drafts], [0, 1, 2])
        self.assertIn(drafts[-1]["output_sha256"], third["step_output_sha256s"])
        self._assert_initial_steps_once(script)
        self.assertEqual(script.count("linking"), 3)
        self.assertEqual(script.count("review"), 3)

    def test_worker_human_revision_rechecks_and_04_publishes_after_state_review(self):
        job_id, revision_id, source_sha, script, review_id, packet = self._content_gate("human_revision")
        self._decide_content(job_id, review_id, packet, decision="revise")
        self.assertEqual(self._run_job(job_id, source_sha, script), "needs_review", self._job_status(job_id))
        artifact = self._assert_state_gate_without_chunk_failure(job_id)
        self.assertNotEqual(artifact["production_receipt"]["candidate_sha256"], packet["candidate_sha256"])
        self.assertEqual(artifact["production_receipt"]["decision"]["kind"], "ai")
        self.assertEqual(artifact["candidate"]["translation"]["blocks"][0]["text"], CORRECT_FIRST)
        self._assert_initial_steps_once(script)
        self.assertEqual(script.count("repair"), 0)
        self.assertEqual(script.count("linking"), 2)
        self.assertEqual(script.count("review"), 2)
        last = [entry for entry in script.inputs if entry["step"] == "review"][-1]["data"]
        self.assertEqual(last["previous_issues"], packet["issues"])
        self.assertEqual(last["history"][:len(packet["history"])], packet["history"])
        self.assertTrue(any(entry["step"] == "human_repair" for entry in last["history"]))
        before = copy.deepcopy(script.calls)
        self._approve_person_state(job_id)
        script.deny_calls = True
        self.assertEqual(self._run_job(job_id, source_sha, script), "completed", self._job_status(job_id))
        self.assertEqual(script.calls, before)
        with psycopg.connect(self.database_url) as conn:
            published = chapter_store.list_published_chapters(conn, job_id=job_id, limit=100)
            self.assertEqual(len(published), 1)
            self.assertEqual(published[0]["revision_id"], str(revision_id))
            self.assertEqual(conn.execute("SELECT count(*) FROM chronicle.canonical_catalogs").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM chronicle.reading_streams WHERE revision_id = %s", (revision_id,)).fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT status FROM chronicle.ingestion_job_stages WHERE job_id = %s AND stage = 'present'", (job_id,)).fetchone()[0], "completed")
            self.assertEqual(conn.execute("SELECT count(*) FROM chronicle.review_items WHERE job_id = %s AND kind = 'chunk_failure'", (job_id,)).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
