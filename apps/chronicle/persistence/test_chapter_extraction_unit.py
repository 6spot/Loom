"""Unit tests for Chronicle C2-R1-T05 whole-chapter extraction (no PostgreSQL).

Covers chapter-production.md sections 3-4 through the T01 contract
validator: whole-chapter prompts (head and tail in every call),
one-shot acceptance of a valid joint product, fail-closed two-round
behavior for missing-body/missing-reference/structure-only candidates,
input/output over-limit refusal without truncation or chunk fallback,
correction-vs-transport accounting, same-chapter ref/ambiguity/time
contract fixtures, and replayable attempt history. Pure functions plus a
fake ``complete(prompt)->str`` callable only: no DB, network, worker, or
real-provider calls.

A passing suite here is mechanical contract evidence only; it never
certifies translation content accuracy.
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
from common import PersistenceError  # noqa: E402

FIXTURES = HERE.parent / "ingestion" / "fixtures" / "c2r1-contract"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def base() -> tuple[dict, dict]:
    return load("request.json"), load("candidate-valid.json")


def tail_text() -> str:
    return load("request.json")["normalized_text"]


class FakeChapterModel:
    """Scripted ``complete(prompt)->str`` callable; records every prompt."""

    def __init__(self, script: list, name: str = "fake-chapter-model") -> None:
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


def candidate_json(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def long_request() -> dict:
    """Synthetic 500-char request to prove the tail travels in prompts."""
    head = "建安十三年，曹操屯江陵。" * 20  # 220 chars
    tail = "章尾核对句：周瑜敗操於赤壁，王命退兵。"
    text = head + "操觀兵赤壁。" * 40 + tail
    assert len(text) > 400
    cut = len(head)
    request = {
        "chapter_id": "ch_" + "ab" * 12,
        "chapter_index": 0,
        "title": "合成章",
        "revision_id": "rev_t05_tail_001",
        "document_id": "doc_t05_tail_001",
        "source_sha256": "11" * 32,
        "normalized_sha256": "22" * 32,
        "normalized_text": text,
        "blocks": [
            {"block_id": "b_001", "kind": "body", "start": 0, "end": cut},
            {"block_id": "b_002", "kind": "body", "start": cut, "end": len(text)},
        ],
        "required_block_ids": ["b_001", "b_002"],
        "plan_version": "c2r1-chapters-v1",
        "limits": C.ChapterLimits().to_dict(),
        "schema_versions": {"candidate": "0.1", "bundle": "0.1"},
    }
    return request


class PromptRenderingTests(unittest.TestCase):
    def test_initial_prompt_carries_whole_chapter_and_tail(self) -> None:
        request = long_request()
        prompt = P.render_chapter_prompt(request)
        text = request["normalized_text"]
        self.assertIn(text[:200], prompt)
        self.assertIn(text[-60:], prompt)  # tail, not just the first 200 chars
        for block in request["blocks"]:
            self.assertIn(block["block_id"], prompt)
            self.assertIn(text[block["start"]:block["end"]], prompt)
        for block_id in request["required_block_ids"]:
            self.assertIn(block_id, prompt)
        self.assertIn(request["chapter_id"], prompt)
        self.assertIn("c2r1-chapter-prompt-v1", prompt)

    def test_correction_prompt_repeats_whole_chapter(self) -> None:
        request = long_request()
        prompt = P.render_chapter_prompt(
            request,
            validation_errors=["translation_coverage: translation misses required source blocks: b_002"],
            previous_candidate={"note": "prior"},
        )
        text = request["normalized_text"]
        self.assertIn(text[-60:], prompt)
        self.assertIn(text[:200], prompt)
        self.assertIn("CORRECTION", prompt)
        self.assertIn("translation_coverage", prompt)

    def test_correction_requires_previous_candidate(self) -> None:
        request, _ = base()
        with self.assertRaises(PersistenceError):
            P.render_chapter_prompt(request, validation_errors=["e"], previous_candidate=None)

    def test_bad_request_fails_closed(self) -> None:
        with self.assertRaises(PersistenceError):
            P.render_chapter_prompt({"chapter_id": "ch_x"})

    def test_compact_diagnostics_bounded(self) -> None:
        errors = [f"translation_coverage: repeated error {i % 3}" for i in range(100)]
        compacted = P.compact_validation_errors(errors)
        self.assertLessEqual(len(compacted), 21)
        self.assertLessEqual(sum(len(e) for e in compacted), 1800 + 160 + 280)


class AcceptOnceTests(unittest.TestCase):
    def test_valid_joint_product_accepted_in_one_round(self) -> None:
        request, candidate = base()
        model = FakeChapterModel([json.dumps(candidate, ensure_ascii=False)])
        result = X.extract_chapter(request, model)
        self.assertTrue(result["accepted"], json.dumps(result["error"], ensure_ascii=False))
        self.assertIsNone(result["error"])
        self.assertEqual(len(result["attempts"]), 1)
        self.assertEqual(result["attempts"][0]["kind"], "initial")
        self.assertEqual(result["correction_rounds_used"], 0)
        self.assertEqual(result["transport_retries"], 0)
        artifact = result["artifact"]
        self.assertEqual(artifact["schema"], "chronicle.chapter-artifact")
        self.assertEqual(artifact["chapter_id"], request["chapter_id"])
        self.assertEqual(
            result["request_fingerprint"], C.request_fingerprint(request)
        )
        fingerprints = result["fingerprints"]
        for key in ("limits", "model", "prompt_version", "source_sha256",
                    "normalized_sha256", "plan_version", "candidate_schema"):
            self.assertIn(key, fingerprints)
        self.assertEqual(fingerprints["model"], model.name)
        # Anchors bind the request text.
        text = request["normalized_text"]
        self.assertTrue(artifact["anchors"])
        for anchor in artifact["anchors"]:
            self.assertEqual(text[anchor["start"]:anchor["end"]], anchor["quote"])
        # History replays cleanly.
        self.assertEqual(X.verify_history(result, request=request), [])
        # Raw response and prompt recorded verbatim with sizes.
        attempt = result["attempts"][0]
        self.assertTrue(attempt["raw_response_chars"] > 0)
        self.assertTrue(attempt["raw_response_bytes"] > 0)
        self.assertTrue(attempt["prompt_chars"] > 0)

    def test_fenced_json_response_accepted(self) -> None:
        request, candidate = base()
        fenced = "```json\n" + json.dumps(candidate, ensure_ascii=False) + "\n```"
        result = X.extract_chapter(request, FakeChapterModel([fenced]))
        self.assertTrue(result["accepted"])

    def test_contract_fixture_validates_same_chapter_discipline(self) -> None:
        # 曹操/操 share ent_001; 公/王 stay contextual; ambiguous has no target.
        request, candidate = base()
        report = C.validate_chapter_candidate(request, candidate)
        self.assertTrue(report["passed"], json.dumps(report["errors"], ensure_ascii=False))
        targets = {m["mention_id"]: m for m in candidate["mentions"]}
        self.assertEqual(targets["m_001"]["target_ref"], "ent_001")
        self.assertEqual(targets["m_002"]["target_ref"], "ent_001")
        self.assertTrue(targets["m_003"]["contextual"])
        self.assertIsNone(targets["m_004"]["target_ref"])
        result = X.extract_chapter(request, FakeChapterModel([json.dumps(candidate)]))
        self.assertTrue(result["accepted"])


class CorrectionTests(unittest.TestCase):
    def test_repair_after_first_failure_then_accept(self) -> None:
        request, candidate = base()
        bad = load("candidate-missing-tail.json")
        model = FakeChapterModel([
            json.dumps(bad, ensure_ascii=False),
            json.dumps(candidate, ensure_ascii=False),
        ])
        result = X.extract_chapter(request, model)
        self.assertTrue(result["accepted"], json.dumps(result["error"], ensure_ascii=False))
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(
            [a["kind"] for a in result["attempts"]], ["initial", "correction"]
        )
        self.assertEqual(result["correction_rounds_used"], 1)
        # Both rounds carried the whole chapter, tail included.
        for prompt in model.prompts:
            self.assertIn(tail_text(), prompt)
        self.assertIn("CORRECTION", model.prompts[1])
        self.assertEqual(X.verify_history(result, request=request), [])

    def test_two_failures_fail_closed_with_records(self) -> None:
        request, _ = base()
        bad = json.dumps(load("candidate-missing-tail.json"), ensure_ascii=False)
        model = FakeChapterModel([bad, bad])
        result = X.extract_chapter(request, model)
        self.assertFalse(result["accepted"])
        self.assertIsNone(result["artifact"])
        self.assertEqual(result["error"]["code"], "validation_failed")
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(result["correction_rounds_used"], 1)
        # Failure records retained for audit.
        self.assertIsNotNone(result["attempts"][0]["validation"])
        self.assertIsNotNone(result["attempts"][1]["validation"])

    def test_translation_only_and_bundle_only_fail_both_rounds(self) -> None:
        request, _ = base()
        for name in ("candidate-translation-only-shape.json", "candidate-bundle-only.json"):
            raw = candidate_json(name)
            result = X.extract_chapter(request, FakeChapterModel([raw, raw]))
            self.assertFalse(result["accepted"], name)
            self.assertEqual(result["error"]["code"], "validation_failed", name)
            self.assertEqual(len(result["attempts"]), 2, name)

    def test_bad_month_rejected_after_correction(self) -> None:
        request, _ = base()
        raw = candidate_json("candidate-bad-month.json")
        result = X.extract_chapter(request, FakeChapterModel([raw, raw]))
        self.assertFalse(result["accepted"])
        detail = result["error"]["message"]
        self.assertIn("month", detail)

    def test_unparseable_twice_reports_parse_failure(self) -> None:
        request, _ = base()
        result = X.extract_chapter(request, FakeChapterModel(["not json {", "still {{{"]))
        self.assertFalse(result["accepted"])
        self.assertEqual(result["error"]["code"], "response_parse")
        self.assertEqual(len(result["attempts"]), 2)

    def test_parse_failure_then_accept(self) -> None:
        request, candidate = base()
        result = X.extract_chapter(
            request,
            FakeChapterModel(["{oops", json.dumps(candidate, ensure_ascii=False)]),
        )
        self.assertTrue(result["accepted"])
        self.assertEqual(result["correction_rounds_used"], 1)


class LimitTests(unittest.TestCase):
    def test_source_over_limit_calls_no_model(self) -> None:
        request, candidate = base()
        tiny = C.ChapterLimits(
            max_source_chars=10,
            max_prompt_chars=262144,
            max_response_chars=524288,
            max_response_bytes=4 * 1024 * 1024,
            max_output_tokens=65536,
        )
        model = FakeChapterModel([json.dumps(candidate, ensure_ascii=False)])
        result = X.extract_chapter(request, model, limits=tiny)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["error"]["code"], "source_over_limit")
        self.assertEqual(model.prompts, [])

    def test_prompt_over_limit_calls_no_model(self) -> None:
        request, candidate = base()
        tiny = C.ChapterLimits(
            max_source_chars=32768,
            max_prompt_chars=10,
            max_response_chars=524288,
            max_response_bytes=4 * 1024 * 1024,
            max_output_tokens=65536,
        )
        model = FakeChapterModel([json.dumps(candidate, ensure_ascii=False)])
        result = X.extract_chapter(request, model, limits=tiny)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["error"]["code"], "prompt_over_limit")
        self.assertEqual(model.prompts, [])

    def test_response_chars_over_limit_fails_without_correction(self) -> None:
        request, candidate = base()
        raw = json.dumps(candidate, ensure_ascii=False)
        tiny = C.ChapterLimits(
            max_source_chars=32768,
            max_prompt_chars=262144,
            max_response_chars=10,
            max_response_bytes=4 * 1024 * 1024,
            max_output_tokens=65536,
        )
        model = FakeChapterModel([raw, raw])
        result = X.extract_chapter(request, model, limits=tiny)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["error"]["code"], "response_over_limit_chars")
        self.assertEqual(len(result["attempts"]), 1)

    def test_response_bytes_over_limit_fails_closed(self) -> None:
        request, candidate = base()
        raw = json.dumps(candidate, ensure_ascii=False)
        byte_len = len(raw.encode("utf-8"))
        tiny = C.ChapterLimits(
            max_source_chars=32768,
            max_prompt_chars=262144,
            max_response_chars=524288,
            max_response_bytes=byte_len - 1,
            max_output_tokens=65536,
        )
        result = X.extract_chapter(request, FakeChapterModel([raw]), limits=tiny)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["error"]["code"], "response_over_limit_bytes")


class TransportTests(unittest.TestCase):
    def test_missing_model_is_typed_failure(self) -> None:
        request, _ = base()
        result = X.extract_chapter(request, None)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["error"]["code"], "missing_model")
        self.assertEqual(result["attempts"], [])

    def test_transport_error_not_retried_here(self) -> None:
        request, candidate = base()
        model = FakeChapterModel(
            [RuntimeError("connection reset"), json.dumps(candidate, ensure_ascii=False)]
        )
        result = X.extract_chapter(request, model)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["error"]["code"], "model_transport_error")
        # One transport call only: no silent retry in this layer (T06 owns it),
        # and no semantic correction consumed either.
        self.assertEqual(len(model.prompts), 1)
        self.assertEqual(len(result["attempts"]), 1)
        self.assertEqual(result["correction_rounds_used"], 0)
        self.assertEqual(result["transport_retries"], 0)
        self.assertIsNotNone(result["attempts"][0]["transport_error"])

    def test_non_text_output_fails_closed(self) -> None:
        request, _ = base()
        result = X.extract_chapter(request, FakeChapterModel([{"not": "text"}]))
        self.assertFalse(result["accepted"])
        self.assertEqual(result["error"]["code"], "model_transport_error")


class HistoryTests(unittest.TestCase):
    def test_tampered_history_detected(self) -> None:
        request, candidate = base()
        result = X.extract_chapter(
            request, FakeChapterModel([json.dumps(candidate, ensure_ascii=False)])
        )
        tampered = copy.deepcopy(result)
        tampered["attempts"][0]["validation"]["passed"] = False
        mismatches = X.verify_history(tampered, request=request)
        self.assertTrue(mismatches)

    def test_empty_history_reported(self) -> None:
        request, _ = base()
        self.assertTrue(X.verify_history({"attempts": []}, request=request))

    def test_fingerprints_bind_execution(self) -> None:
        request, candidate = base()
        model = FakeChapterModel([json.dumps(candidate, ensure_ascii=False)],
                                 name="unit-model-v1")
        result = X.extract_chapter(request, model)
        fingerprints = result["fingerprints"]
        self.assertEqual(fingerprints["model"], "unit-model-v1")
        self.assertEqual(fingerprints["prompt_version"], "c2r1-chapter-prompt-v1")
        self.assertEqual(fingerprints["plan_version"], "c2r1-chapters-v1")
        self.assertEqual(fingerprints["source_sha256"], request["source_sha256"])
        self.assertEqual(
            fingerprints["candidate_schema"], "chronicle.chapter-candidate/0.1"
        )


if __name__ == "__main__":
    unittest.main()
