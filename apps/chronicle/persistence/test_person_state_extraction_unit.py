"""Unit tests for Chronicle C2-R3-T02 person-state joint extraction (no PostgreSQL).

Covers the third-round whole-chapter path: one request produces a
``chronicle.chapter-candidate / 0.3`` joint product (translation + C0 bundle +
reading annotations + ``person_states``), accepted only through the T01
``person_state_contract`` validator/acceptance. Exercises one-shot success, a
whole-chapter correction that repairs a person-state failure, a second failure
that fails closed with consumer-side error categories, missing
``person_states`` / capacity / unknown-enum whole-product failure, the 0.2
sub-contract rejection, and the preserved 0.1/0.2 regression paths.

Pure functions plus a fake ``complete(prompt)->str`` callable only: no DB,
network, worker, or real-provider calls. A passing suite here is mechanical
contract evidence only; it never certifies translation or historical content
accuracy.
"""

from __future__ import annotations

import copy
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
import person_state_contract as PS  # noqa: E402
import reading_contract as R  # noqa: E402

PERSON_STATE_FIXTURES = HERE.parent / "ingestion" / "fixtures" / "c2r3-contract"
READING_FIXTURES = HERE.parent / "ingestion" / "fixtures" / "c2r2-contract"
FIRST_ROUND_FIXTURES = HERE.parent / "ingestion" / "fixtures" / "c2r1-contract"


def load(directory: Path, name: str) -> dict:
    return json.loads((directory / name).read_text(encoding="utf-8"))


def person_state_request() -> dict:
    return load(PERSON_STATE_FIXTURES, "request.json")


def person_state_candidate(name: str) -> str:
    return (PERSON_STATE_FIXTURES / name).read_text(encoding="utf-8")


class FakeChapterModel:
    """Scripted ``complete(prompt)->str`` callable; records every prompt."""

    def __init__(self, script: list, name: str = "fake-person-state-model") -> None:
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


class PersonStatePromptTests(unittest.TestCase):
    def test_person_state_prompt_carries_whole_chapter_and_both_guides(self) -> None:
        request = person_state_request()
        prompt = P.render_chapter_prompt(request)
        text = request["normalized_text"]
        self.assertIn(text[:40], prompt)
        self.assertIn(text[-20:], prompt)
        self.assertIn(P.PERSON_STATE_PROMPT_VERSION, prompt)
        self.assertIn("READING ANNOTATION SHAPE", prompt)
        self.assertNotIn("READING ANNOTATION SHAPE (0.2 only;", prompt)
        self.assertIn("PERSON STATE SHAPE", prompt)
        self.assertIn("recommendation", prompt)
        self.assertIn("attest", prompt)
        self.assertIn("Never write start/end offsets", prompt)

    def test_0_2_request_keeps_reading_prompt_without_person_guide(self) -> None:
        request = load(READING_FIXTURES, "request.json")
        prompt = P.render_chapter_prompt(request)
        self.assertIn(P.READING_PROMPT_VERSION, prompt)
        self.assertIn("READING ANNOTATION SHAPE", prompt)
        self.assertNotIn("PERSON STATE SHAPE", prompt)

    def test_0_1_request_keeps_first_round_prompt(self) -> None:
        request = load(FIRST_ROUND_FIXTURES, "request.json")
        prompt = P.render_chapter_prompt(request)
        self.assertIn(P.PROMPT_VERSION, prompt)
        self.assertNotIn("PERSON STATE SHAPE", prompt)
        self.assertNotIn("READING ANNOTATION SHAPE", prompt)


class PersonStateAcceptanceTests(unittest.TestCase):
    def test_valid_person_state_product_accepted_in_one_round(self) -> None:
        request = person_state_request()
        raw = person_state_candidate("candidate-valid.json")
        model = FakeChapterModel([raw])
        result = X.extract_chapter(request, model)
        self.assertTrue(result["accepted"], json.dumps(result["error"], ensure_ascii=False))
        self.assertIsNone(result["error"])
        self.assertEqual(len(result["attempts"]), 1)
        self.assertEqual(result["correction_rounds_used"], 0)
        artifact = result["artifact"]
        self.assertEqual(artifact["schema"], "chronicle.chapter-artifact")
        self.assertEqual(artifact["version"], "0.3")
        self.assertEqual(artifact["candidate"]["version"], "0.3")
        self.assertIn("person_states", artifact["candidate"])
        self.assertEqual(len(artifact["reading_units"]), 3)
        self.assertTrue(artifact["person_state_candidates"])
        self.assertIn("person_states_sha256", artifact)
        self.assertEqual(
            result["fingerprints"]["candidate_schema"],
            "chronicle.chapter-candidate/0.3",
        )
        self.assertEqual(
            result["fingerprints"]["prompt_version"], P.PERSON_STATE_PROMPT_VERSION
        )
        self.assertEqual(
            result["fingerprints"]["person_state_schema"],
            f"{PS.PERSON_STATE_SCHEMA}/{PS.PERSON_STATE_VERSION}",
        )
        self.assertEqual(
            result["fingerprints"]["person_state_contract"], PS.CONTRACT_VERSION
        )
        self.assertEqual(
            result["fingerprints"]["reading_schema"],
            f"{R.READING_SCHEMA}/{R.READING_VERSION}",
        )
        # The unit-phase bindings mirror the translation blocks exactly.
        block_ids = [
            b["block_id"] for b in artifact["candidate"]["translation"]["blocks"]
        ]
        self.assertEqual(
            [u["block_id"] for u in artifact["candidate"]["person_states"]["unit_phases"]],
            block_ids,
        )
        self.assertEqual(X.verify_history(result, request=request), [])


class PersonStateCorrectionTests(unittest.TestCase):
    def test_person_state_failure_then_correction_accepts(self) -> None:
        request = person_state_request()
        model = FakeChapterModel(
            [
                person_state_candidate("candidate-missing-unit-phase.json"),
                person_state_candidate("candidate-valid.json"),
            ]
        )
        result = X.extract_chapter(request, model)
        self.assertTrue(result["accepted"], json.dumps(result["error"], ensure_ascii=False))
        self.assertEqual([a["kind"] for a in result["attempts"]], ["initial", "correction"])
        self.assertEqual(result["correction_rounds_used"], 1)
        # Both rounds re-send the whole chapter, and the correction carries the
        # person-state diagnosis (never a state-array-only regeneration).
        for prompt in model.prompts:
            self.assertIn(request["normalized_text"], prompt)
            self.assertIn("PERSON STATE SHAPE", prompt)
        self.assertIn("CORRECTION", model.prompts[1])
        self.assertIn("person_state_coverage", model.prompts[1])
        self.assertEqual(X.verify_history(result, request=request), [])

    def test_two_person_state_failures_fail_closed_with_categories(self) -> None:
        request = person_state_request()
        raw = person_state_candidate("candidate-missing-unit-phase.json")
        result = X.extract_chapter(request, FakeChapterModel([raw, raw]))
        self.assertFalse(result["accepted"])
        self.assertIsNone(result["artifact"])
        self.assertEqual(result["error"]["code"], "validation_failed")
        self.assertEqual(len(result["attempts"]), 2)
        self.assertIn("person_state_coverage", result["error"]["categories"])
        self.assertIsNotNone(result["attempts"][0]["validation"])
        self.assertIsNotNone(result["attempts"][1]["validation"])

    def test_each_negative_fixture_is_categorized(self) -> None:
        cases = {
            "candidate-unknown-ref.json": "person_state_refs",
            "candidate-wrong-subject.json": "person_state_types",
            "candidate-recommendation-start.json": "person_state_types",
            "candidate-unproven-continuity.json": "person_state_continuity",
            "candidate-phase-cycle.json": "person_state_phase",
            "candidate-canonical-id.json": "canonical_id",
        }
        for name, category in cases.items():
            with self.subTest(fixture=name):
                request = person_state_request()
                raw = person_state_candidate(name)
                result = X.extract_chapter(request, FakeChapterModel([raw, raw]))
                self.assertFalse(result["accepted"])
                self.assertIn(category, result["error"]["categories"])


class PersonStateFailureTests(unittest.TestCase):
    def test_missing_person_states_rejects_the_whole_product(self) -> None:
        request = person_state_request()
        candidate = load(PERSON_STATE_FIXTURES, "candidate-valid.json")
        candidate.pop("person_states")
        result = X.extract_chapter(
            request, FakeChapterModel([json.dumps(candidate, ensure_ascii=False)] * 2)
        )
        self.assertFalse(result["accepted"])
        self.assertIsNone(result["artifact"])
        self.assertIn("schema_validation", result["error"]["categories"])

    def test_fact_capacity_overflow_fails_closed_as_limits(self) -> None:
        request = person_state_request()
        candidate = load(PERSON_STATE_FIXTURES, "candidate-valid.json")
        template = candidate["person_states"]["facts"][0]
        facts = []
        for index in range(1, PS.PersonStateLimits().max_facts + 2):
            fact = copy.deepcopy(template)
            fact["fact_id"] = f"pf_{index:03d}"
            facts.append(fact)
        candidate["person_states"]["facts"] = facts
        result = X.extract_chapter(
            request, FakeChapterModel([json.dumps(candidate, ensure_ascii=False)] * 2)
        )
        self.assertFalse(result["accepted"])
        self.assertIsNone(result["artifact"])
        self.assertIn("limits", result["error"]["categories"])

    def test_unknown_enum_fails_closed(self) -> None:
        request = person_state_request()
        candidate = load(PERSON_STATE_FIXTURES, "candidate-valid.json")
        candidate["person_states"]["facts"][0]["operation"] = "promote"
        result = X.extract_chapter(
            request, FakeChapterModel([json.dumps(candidate, ensure_ascii=False)] * 2)
        )
        self.assertFalse(result["accepted"])
        self.assertIn("person_state_types", result["error"]["categories"])

    def test_0_2_payload_cannot_satisfy_0_3(self) -> None:
        request = person_state_request()
        legacy = (READING_FIXTURES / "candidate-valid.json").read_text(encoding="utf-8")
        result = X.extract_chapter(request, FakeChapterModel([legacy, legacy]))
        self.assertFalse(result["accepted"])
        self.assertIsNone(result["artifact"])
        self.assertEqual(result["error"]["code"], "validation_failed")
        self.assertIn("schema_validation", result["error"]["categories"])

    def test_unknown_candidate_version_fails_closed_before_model(self) -> None:
        request = person_state_request()
        request["schema_versions"] = {"candidate": "9.9", "bundle": "0.1"}
        model = FakeChapterModel([person_state_candidate("candidate-valid.json")])
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


class PersonStateLimitsTests(unittest.TestCase):
    def test_person_state_limits_are_bound_into_fingerprints(self) -> None:
        request = person_state_request()
        result = X.extract_chapter(
            request, FakeChapterModel([person_state_candidate("candidate-valid.json")])
        )
        self.assertTrue(result["accepted"])
        fingerprints = result["fingerprints"]
        self.assertEqual(
            fingerprints["person_state_limits"]["max_phases"],
            PS.PersonStateLimits().max_phases,
        )
        self.assertEqual(
            fingerprints["person_state_limits"]["max_facts"],
            PS.PersonStateLimits().max_facts,
        )
        self.assertEqual(
            result["fingerprints"]["extraction_version"],
            X.PERSON_STATE_EXTRACTION_VERSION,
        )


if __name__ == "__main__":
    unittest.main()
