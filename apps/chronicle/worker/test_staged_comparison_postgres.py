"""Real Runner/PostgreSQL regressions for fixed-set model comparisons."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
for path in (str(HERE), str(HERE.parent / "persistence")):
    if path not in sys.path:
        sys.path.insert(0, path)

import chapter_content_review
import chapter_production_store as store
from model_provider import ModelProviderError
import staged_pipeline_fixture as fixture
import test_staged_chapter_pipeline_postgres as pipeline

SECOND_TRANSLATION = "建安三年，孙策任命周瑜为建威中郎将。"
EXPECTED_CALLS = Counter({
    ("translation", "translator_a"): 1, ("translation", "translator_b"): 1,
    ("extraction", "executor"): 1,
    ("comparison", "comparator_a"): 1, ("comparison", "comparator_b"): 1,
    ("linking", "executor"): 1, ("review", "reviewer_0"): 1,
})


class ComparisonModels(fixture.ScriptedModels):
    """Two complete prose versions plus independent comparison reports."""
    def __init__(self, *, disagreement=None, fail_comparator=False):
        super().__init__()
        self.disagreement = disagreement
        self.fail_comparator = fail_comparator
        profiles = copy.deepcopy(self.models.profiles)
        for slot in ("translator_a", "translator_b", "comparator_a", "comparator_b"):
            profiles[slot] = {**profiles["executor"], "model": "comparison-fixture-" + slot}
        steps = {**self.models.steps, "translation": ("translator_a", "translator_b"),
                 "comparison": ("comparator_a", "comparator_b")}
        providers = {(step, slot): fixture._StepModel(self, step, slot)
                     for step, slots in steps.items() for slot in slots}
        self.models = replace(self.models, profiles=profiles, steps=steps, providers=providers)

    def complete(self, expected_step, slot, prompt):
        if expected_step != "comparison":
            raw = super().complete(expected_step, slot, prompt)
            if expected_step == "translation" and slot == "translator_b":
                raw = raw.replace(fixture.CORRECT_FIRST, SECOND_TRANSLATION, 1)
            return raw
        step, source, data = fixture.parse_prompt(prompt)
        if step != "comparison" or data["step"] != "translation":
            raise AssertionError("only the two translation candidates need comparison")
        with self._lock:
            self.calls[(step, slot)] += 1
            attempt = self.calls[(step, slot)]
            self.inputs.append({"step": step, "slot": slot, "attempt": attempt,
                                "source": copy.deepcopy(source), "data": copy.deepcopy(data)})
        if self.deny_calls:
            raise AssertionError("the frozen comparison must be adopted without another call")
        if self.fail_comparator and slot == "comparator_b" and attempt == 1:
            raise ModelProviderError("injected comparison transport failure", raw_text="{\"partial_comparison\":",
                                     receipt={"status": "failed", "usage": None, "http_attempts": 1})
        if len(data["candidates"]) != 2:
            raise AssertionError("comparison must receive the complete fixed candidate set")
        selected_index = 0 if self.disagreement == "different" and slot == "comparator_b" else 1
        evidence = [fragment["id"] for fragment in source["source_scope"]["fragments"]
                    if fragment["role"] == "body"][:1]
        differences = []
        for index, candidate in enumerate(data["candidates"]):
            assessment = "selected" if index == selected_index else "compatible"
            if self.disagreement == "minority" and slot == "comparator_b" and index != selected_index:
                assessment = "disputed"
            differences.append({
                "candidate_sha256": candidate["candidate_sha256"], "assessment": assessment,
                "rationale": f"{slot} 核对策授瑜的主语与任命关系，保留第 {index + 1} 稿比较理由。",
                "evidence": evidence,
            })
        return json.dumps({"candidate_set_sha256": data["candidate_set_sha256"],
                           "selected_sha256": data["candidates"][selected_index]["candidate_sha256"],
                           "differences": differences}, ensure_ascii=False)


class StagedComparisonPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control_url = pipeline.legacy._control_url()

    setUp = pipeline.StagedChapterPipelinePostgresTests.setUp
    tearDown = pipeline.StagedChapterPipelinePostgresTests.tearDown
    _queue_job = pipeline.StagedChapterPipelinePostgresTests._queue_job
    _prepared_extract = pipeline.StagedChapterPipelinePostgresTests._prepared_extract
    _extract = pipeline.StagedChapterPipelinePostgresTests._extract
    _records = pipeline.StagedChapterPipelinePostgresTests._records
    _accepted = pipeline.StagedChapterPipelinePostgresTests._accepted
    _counts = pipeline.StagedChapterPipelinePostgresTests._counts

    def _completed(self, records, step):
        return [record for record in records if record["artifact_type"] == store.STEP_TYPE
                and record["step"] == step and record["status"] == "completed"]

    def _assert_complete_comparison_history(self, history, records):
        expected = self._completed(records, "translation") + self._completed(records, "comparison")
        self.assertEqual(len(expected), 4)
        observed = {entry["output_sha256"]: entry for entry in history}
        for record in expected:
            self.assertIn(record["output_sha256"], observed)
            self.assertEqual(observed[record["output_sha256"]]["parsed"], record["parsed"])
        for comparison in self._completed(records, "comparison"):
            self.assertEqual(len(comparison["parsed"]["differences"]), 2)
            self.assertTrue(all(item["rationale"] and item["evidence"] for item in comparison["parsed"]["differences"]))

    def test_agreed_comparison_selects_second_version_and_keeps_every_candidate(self):
        ctx = self._prepared_extract()
        script = ComparisonModels()
        self.assertEqual(self._extract(ctx, script), "ok")
        self.assertEqual(script.calls, EXPECTED_CALLS)
        records = self._records(ctx)
        translated = {record["slot"]: record for record in self._completed(records, "translation")}
        self.assertEqual(set(translated), {"translator_a", "translator_b"})
        self.assertTrue(translated["translator_a"]["raw_text"].startswith(fixture.CORRECT_FIRST))
        self.assertTrue(translated["translator_b"]["raw_text"].startswith(SECOND_TRANSLATION))
        selected_sha = translated["translator_b"]["output_sha256"]
        for comparison in self._completed(records, "comparison"):
            self.assertEqual(comparison["parsed"]["selected_sha256"], selected_sha)
        artifact = self._accepted(ctx)[0]["artifact"]
        self.assertEqual(artifact["candidate"]["translation"]["blocks"][0]["text"], SECOND_TRANSLATION)
        history = next(entry for entry in script.inputs if entry["step"] == "review")["data"]["history"]
        self._assert_complete_comparison_history(history, records)
        bound = set(artifact["production_receipt"]["step_output_sha256s"])
        self.assertTrue({record["output_sha256"] for record in self._completed(records, "translation") + self._completed(records, "comparison")} <= bound)
        self.assertEqual(self._counts(ctx), {"runs": 1, "reviews": 0, "published": 0})

    def test_conflicting_or_minority_comparison_cannot_be_overruled_by_review_pass(self):
        for disagreement in ("different", "minority"):
            with self.subTest(disagreement=disagreement):
                ctx = self._prepared_extract()
                script = ComparisonModels(disagreement=disagreement)
                self.assertEqual(self._extract(ctx, script), "needs_review")
                self.assertEqual(script.calls, EXPECTED_CALLS)
                records = self._records(ctx)
                self.assertEqual(self._accepted(ctx), [])
                self.assertFalse(any(record["artifact_type"] == store.ACCEPTANCE_TYPE for record in records))
                reports = self._completed(records, "review")
                self.assertEqual([record["parsed"]["verdict"] for record in reports], ["pass"])
                with psycopg.connect(self.database_url) as conn:
                    rows = conn.execute("SELECT review_id, kind, status FROM chronicle.review_items WHERE job_id=%s", (ctx["job_id"],)).fetchall()
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0][1:], ("stage_gate", "open"))
                    frozen = chapter_content_review.read_content_review(conn, rows[0][0])
                self.assertEqual(frozen["payload"]["scope"], "chapter_content")
                packet = frozen["packet"]
                self.assertTrue(any(issue.get("comparison_disputed") is True for issue in packet["issues"]))
                self._assert_complete_comparison_history(packet["history"], records)
                self.assertTrue(all(report["output_sha256"] in packet["step_output_sha256s"] for report in reports))
                if disagreement == "different":
                    self.assertEqual(len({record["parsed"]["selected_sha256"] for record in self._completed(records, "comparison")}), 2)
                else:
                    self.assertEqual(len({record["parsed"]["selected_sha256"] for record in self._completed(records, "comparison")}), 1)
                    self.assertEqual(sum(item["assessment"] == "disputed" for record in self._completed(records, "comparison") for item in record["parsed"]["differences"]), 1)
                self.assertEqual(self._counts(ctx), {"runs": 0, "reviews": 1, "published": 0})
                script.deny_calls = True
                self.assertEqual(self._extract(ctx, script), "needs_review")
                self.assertEqual(script.calls, EXPECTED_CALLS)
                self.assertEqual(self._counts(ctx)["reviews"], 1)

    def test_failed_comparator_retries_only_its_slot_and_retains_failed_result(self):
        ctx = self._prepared_extract()
        script = ComparisonModels(fail_comparator=True)
        self.assertEqual(self._extract(ctx, script), "failed")
        self.assertEqual(self._accepted(ctx), [])
        self.assertEqual(script.count("translation"), 2)
        self.assertEqual(script.count("extraction"), 1)
        self.assertEqual(script.count("comparison"), 2)
        self.assertEqual(script.count("linking"), 0)
        self.assertEqual(script.count("review"), 0)
        self.assertEqual(self._extract(ctx, script), "ok")
        expected = EXPECTED_CALLS.copy()
        expected[("comparison", "comparator_b")] = 2
        self.assertEqual(script.calls, expected)
        records = self._records(ctx)
        failed = [record for record in records if record["artifact_type"] == store.STEP_TYPE
                  and record["step"] == "comparison" and record["status"] == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["slot"], "comparator_b")
        self.assertEqual(failed[0]["raw_text"], "{\"partial_comparison\":")
        history = next(entry for entry in script.inputs if entry["step"] == "review")["data"]["history"]
        self._assert_complete_comparison_history(history, records)
        failed_history = next(entry for entry in history if entry["output_sha256"] == failed[0]["output_sha256"])
        self.assertEqual(failed_history["raw_text"], failed[0]["raw_text"])
        artifact = self._accepted(ctx)[0]["artifact"]
        self.assertEqual(artifact["candidate"]["translation"]["blocks"][0]["text"], SECOND_TRANSLATION)
        self.assertIn(failed[0]["output_sha256"], artifact["production_receipt"]["step_output_sha256s"])
        self.assertEqual(self._counts(ctx), {"runs": 2, "reviews": 0, "published": 0})

    def test_invalid_comparison_objection_survives_link_failure_and_resume(self):
        class InvalidComparison(ComparisonModels):
            def __init__(self):
                super().__init__()
                self.failures = {("linking", "executor"): {1}}

            def complete(self, expected_step, slot, prompt):
                raw = super().complete(expected_step, slot, prompt)
                if expected_step == "comparison" and slot == "comparator_b" and self.count("comparison", slot) == 1:
                    report = json.loads(raw)
                    report["differences"][0]["assessment"] = "disputed"
                    del report["candidate_set_sha256"]
                    return json.dumps(report, ensure_ascii=False)
                return raw

        ctx = self._prepared_extract()
        script = InvalidComparison()
        self.assertEqual(self._extract(ctx, script), "failed")
        self.assertEqual(script.count("comparison", "comparator_b"), 1)
        self.assertEqual(self._extract(ctx, script), "needs_review")
        self.assertEqual(script.count("comparison", "comparator_b"), 1)
        self.assertEqual(script.count("translation"), 2)
        self.assertEqual(script.count("extraction"), 1)
        self.assertEqual(script.count("linking"), 2)
        self.assertEqual(script.count("review"), 1)
        records = self._records(ctx)
        invalid = [r for r in records if r["artifact_type"] == store.STEP_TYPE and r["status"] == "invalid"]
        self.assertEqual(len(invalid), 1)
        self.assertEqual(invalid[0]["step"], "comparison")
        self.assertEqual(invalid[0]["parsed"]["differences"][0]["assessment"], "disputed")
        self.assertEqual([r["parsed"]["verdict"] for r in self._completed(records, "review")], ["pass"])
        self.assertEqual(self._accepted(ctx), [])
        with psycopg.connect(self.database_url) as conn:
            review_id = conn.execute("SELECT review_id FROM chronicle.review_items WHERE job_id=%s", (ctx["job_id"],)).fetchone()[0]
            packet = chapter_content_review.read_content_review(conn, review_id)["packet"]
        self.assertTrue(any(issue.get("comparison_disputed") for issue in packet["issues"]))
        self.assertIn(invalid[0]["output_sha256"], packet["step_output_sha256s"])
        calls = script.calls.copy()
        script.deny_calls = True
        self.assertEqual(self._extract(ctx, script), "needs_review")
        self.assertEqual(script.calls, calls)


if __name__ == "__main__":
    unittest.main()
