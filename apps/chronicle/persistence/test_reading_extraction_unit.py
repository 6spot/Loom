"""Unit tests for Chronicle C2-R2-T03 reading joint extraction (no PostgreSQL).

Covers the second-round whole-chapter path: one request produces a
``chronicle.chapter-candidate / 0.2`` joint product (translation + bundle +
reading annotations), accepted only through the T01 ``reading_contract``
validator/acceptance. Exercises one-shot success, one whole-chapter
correction that repairs a reading failure, a second failure that fails
closed with consumer-side error categories (missing unit, overlapping span,
wrong current-time basis, bad role), refusal to silently downgrade 0.2 to
0.1, and the preserved 0.1 first-round regression path.

Pure functions plus a fake ``complete(prompt)->str`` callable only: no DB,
network, worker, or real-provider calls. A passing suite here is mechanical
contract evidence only; it never certifies translation content accuracy.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import chapter_contract as C  # noqa: E402
import chapter_extraction as X  # noqa: E402
import chapter_prompt as P  # noqa: E402
import reading_contract as R  # noqa: E402

READING_FIXTURES = HERE.parent / "ingestion" / "fixtures" / "c2r2-contract"
FIRST_ROUND_FIXTURES = HERE.parent / "ingestion" / "fixtures" / "c2r1-contract"


def load(directory: Path, name: str) -> dict:
    return json.loads((directory / name).read_text(encoding="utf-8"))


def reading_request() -> dict:
    return load(READING_FIXTURES, "request.json")


def reading_candidate(name: str) -> str:
    return (READING_FIXTURES / name).read_text(encoding="utf-8")


class FakeChapterModel:
    """Scripted ``complete(prompt)->str`` callable; records every prompt."""

    def __init__(self, script: list, name: str = "fake-reading-model") -> None:
        self._script = list(script)
        self.name = name
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._script:
            raise AssertionError("fake model called more times than scripted")
        action = self._script.pop(0)
        if isinstance(action, Exception):
            raise action
        if callable(action):
            return action(prompt)
        return action


class ReadingPromptTests(unittest.TestCase):
    def test_reading_prompt_carries_whole_chapter_and_reading_guide(self) -> None:
        request = reading_request()
        prompt = P.render_chapter_prompt(request)
        text = request["normalized_text"]
        self.assertIn(text[:40], prompt)
        self.assertIn(text[-20:], prompt)
        self.assertIn(P.READING_PROMPT_VERSION, prompt)
        self.assertIn("READING ANNOTATION SHAPE", prompt)
        self.assertIn("current_event_refs", prompt)
        self.assertIn("Never write start/end offsets", prompt)

    def test_0_1_request_keeps_first_round_prompt(self) -> None:
        request = load(FIRST_ROUND_FIXTURES, "request.json")
        prompt = P.render_chapter_prompt(request)
        self.assertIn(P.PROMPT_VERSION, prompt)
        self.assertNotIn("READING ANNOTATION SHAPE", prompt)


class ReadingAcceptanceTests(unittest.TestCase):
    def test_valid_reading_product_accepted_in_one_round(self) -> None:
        request = reading_request()
        raw = reading_candidate("candidate-valid.json")
        model = FakeChapterModel([raw])
        result = X.extract_chapter(request, model)
        self.assertTrue(result["accepted"], json.dumps(result["error"], ensure_ascii=False))
        self.assertIsNone(result["error"])
        self.assertEqual(len(result["attempts"]), 1)
        self.assertEqual(result["correction_rounds_used"], 0)
        artifact = result["artifact"]
        self.assertEqual(artifact["schema"], "chronicle.chapter-artifact")
        self.assertEqual(artifact["version"], "0.2")
        self.assertEqual(artifact["candidate"]["version"], "0.2")
        self.assertEqual(len(artifact["reading_units"]), 3)
        self.assertEqual(
            result["fingerprints"]["candidate_schema"],
            "chronicle.chapter-candidate/0.2",
        )
        self.assertEqual(
            result["fingerprints"]["prompt_version"], P.READING_PROMPT_VERSION
        )
        # The reading units mirror the translation blocks exactly.
        block_ids = [b["block_id"] for b in artifact["candidate"]["translation"]["blocks"]]
        self.assertEqual(
            [u["block_id"] for u in artifact["reading_units"]], block_ids
        )
        self.assertEqual(X.verify_history(result, request=request), [])

    def test_reading_span_segments_reassemble_translation(self) -> None:
        request = reading_request()
        result = X.extract_chapter(
            request, FakeChapterModel([reading_candidate("candidate-valid.json")])
        )
        self.assertTrue(result["accepted"])
        blocks = {
            block["block_id"]: block["text"]
            for block in result["artifact"]["candidate"]["translation"]["blocks"]
        }
        for unit in result["artifact"]["reading_units"]:
            joined = "".join(segment["text"] for segment in unit["segments"])
            self.assertEqual(joined, blocks[unit["block_id"]])


class ReadingCorrectionTests(unittest.TestCase):
    def test_reading_failure_then_correction_accepts(self) -> None:
        request = reading_request()
        model = FakeChapterModel(
            [
                reading_candidate("candidate-missing-unit.json"),
                reading_candidate("candidate-valid.json"),
            ]
        )
        result = X.extract_chapter(request, model)
        self.assertTrue(result["accepted"], json.dumps(result["error"], ensure_ascii=False))
        self.assertEqual([a["kind"] for a in result["attempts"]], ["initial", "correction"])
        self.assertEqual(result["correction_rounds_used"], 1)
        # Both rounds re-send the whole chapter, including the tail, and the
        # correction carries the reading diagnosis.
        for prompt in model.prompts:
            self.assertIn(request["normalized_text"], prompt)
        self.assertIn("CORRECTION", model.prompts[1])
        self.assertIn("reading_coverage", model.prompts[1])
        self.assertEqual(X.verify_history(result, request=request), [])

    def test_two_reading_failures_fail_closed_with_categories(self) -> None:
        request = reading_request()
        raw = reading_candidate("candidate-overlap-span.json")
        result = X.extract_chapter(request, FakeChapterModel([raw, raw]))
        self.assertFalse(result["accepted"])
        self.assertIsNone(result["artifact"])
        self.assertEqual(result["error"]["code"], "validation_failed")
        self.assertEqual(len(result["attempts"]), 2)
        self.assertIn("reading_spans", result["error"]["categories"])
        # Failure records retained for audit.
        self.assertIsNotNone(result["attempts"][0]["validation"])
        self.assertIsNotNone(result["attempts"][1]["validation"])

    def test_metadata_role_error_never_returns_translation_success(self) -> None:
        # Acceptance: metadata errors cannot be dropped and reported as a
        # successful translation. A forged entity role must reject both rounds.
        request = reading_request()
        raw = reading_candidate("candidate-forged-role.json")
        result = X.extract_chapter(request, FakeChapterModel([raw, raw]))
        self.assertFalse(result["accepted"])
        self.assertIsNone(result["artifact"])
        self.assertIn("reading_context", result["error"]["categories"])

    def test_wrong_current_time_basis_is_categorized(self) -> None:
        request = reading_request()
        raw = reading_candidate("candidate-retrospective-as-time.json")
        result = X.extract_chapter(request, FakeChapterModel([raw, raw]))
        self.assertFalse(result["accepted"])
        self.assertIn("reading_time", result["error"]["categories"])

    def test_missing_unit_is_categorized(self) -> None:
        request = reading_request()
        raw = reading_candidate("candidate-missing-unit.json")
        result = X.extract_chapter(request, FakeChapterModel([raw, raw]))
        self.assertFalse(result["accepted"])
        self.assertIn("reading_coverage", result["error"]["categories"])


class VersionDisciplineTests(unittest.TestCase):
    def test_version_registry_declares_0_2_production_and_keeps_0_1(self) -> None:
        self.assertEqual(C.PRODUCTION_CANDIDATE_VERSION, "0.2")
        self.assertEqual(C.PRODUCTION_ARTIFACT_VERSION, "0.2")
        self.assertEqual(tuple(C.CANDIDATE_VERSIONS), ("0.1", "0.2"))
        self.assertEqual(tuple(C.ARTIFACT_VERSIONS), ("0.1", "0.2"))
        self.assertTrue(C.CANDIDATE_VERSION == "0.1")
        self.assertTrue(
            C.candidate_schema_for("0.2")["$id"].endswith("candidate-v0.2.schema.json")
        )
        self.assertTrue(
            C.artifact_schema_for("0.2")["$id"].endswith("artifact-v0.2.schema.json")
        )
        self.assertIn("0.2", C.candidate_schema_registry())
        with self.assertRaises(C.PersistenceError):
            C.candidate_schema_for("0.3")

    def test_refuses_silent_downgrade_from_0_2_to_0_1(self) -> None:
        request = reading_request()
        legacy = json.dumps(
            load(FIRST_ROUND_FIXTURES, "candidate-valid.json"), ensure_ascii=False
        )
        result = X.extract_chapter(request, FakeChapterModel([legacy, legacy]))
        self.assertFalse(result["accepted"])
        self.assertIsNone(result["artifact"])
        self.assertEqual(result["error"]["code"], "validation_failed")
        # The 0.1 payload can never satisfy the 0.2 contract.
        self.assertIn("schema_validation", result["error"]["categories"])

    def test_unknown_candidate_version_fails_closed_before_model(self) -> None:
        request = reading_request()
        request["schema_versions"] = {"candidate": "9.9", "bundle": "0.1"}
        model = FakeChapterModel([reading_candidate("candidate-valid.json")])
        result = X.extract_chapter(request, model)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["error"]["code"], "unsupported_candidate_version")
        self.assertEqual(model.prompts, [])

    def test_0_1_request_still_uses_frozen_first_round_contract(self) -> None:
        request = load(FIRST_ROUND_FIXTURES, "request.json")
        candidate = json.dumps(
            load(FIRST_ROUND_FIXTURES, "candidate-valid.json"), ensure_ascii=False
        )
        result = X.extract_chapter(request, FakeChapterModel([candidate]))
        self.assertTrue(result["accepted"], json.dumps(result["error"], ensure_ascii=False))
        self.assertEqual(result["artifact"]["version"], "0.1")
        self.assertEqual(
            result["fingerprints"]["candidate_schema"],
            "chronicle.chapter-candidate/0.1",
        )
        self.assertEqual(result["fingerprints"]["prompt_version"], P.PROMPT_VERSION)


class ReadingLimitsTests(unittest.TestCase):
    def test_reading_limits_are_bound_into_fingerprints(self) -> None:
        request = reading_request()
        result = X.extract_chapter(
            request, FakeChapterModel([reading_candidate("candidate-valid.json")])
        )
        self.assertTrue(result["accepted"])
        fingerprints = result["fingerprints"]
        self.assertEqual(
            fingerprints["reading_schema"],
            f"{R.READING_SCHEMA}/{R.READING_VERSION}",
        )
        self.assertEqual(
            fingerprints["reading_limits"]["max_event_spans"],
            R.ReadingLimits().max_event_spans,
        )


if __name__ == "__main__":
    unittest.main()
