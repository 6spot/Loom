from __future__ import annotations

import json
import unittest

from coverage_v02 import CoverageV02Extractor, build_coverage_prompt, object_counts


class FakeProvider:
    name = "fake"

    def __init__(self, response: dict):
        self.response = json.dumps(response, ensure_ascii=False)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def staged_bundle() -> dict:
    return {
        "schema_version": "0.1",
        "source": {
            "temp_id": "src_777",
            "kind": "source",
            "source_type": "book",
            "title": "三国志·魏书·武帝纪",
            "language": "lzh",
            "metadata": {},
            "extraction": {"method": "model"},
        },
        "entities": [],
        "events": [],
        "claims": [],
        "warnings": [],
    }


class CoverageV02Tests(unittest.TestCase):
    def test_prompt_contains_source_and_pass1_but_no_reference_answer(self) -> None:
        prompt = build_coverage_prompt(
            "十二月，孙权为备攻合肥。",
            {"chronology": {"normalized_year": 208}},
            {"claim": {"predicates": {"allowed": ["attacked"]}}},
            {"type": "object"},
            staged_bundle(),
        )
        self.assertIn("十二月，孙权为备攻合肥。", prompt)
        self.assertIn("PASS-1 STAGED BUNDLE", prompt)
        self.assertIn("sentence-by-sentence", prompt)
        self.assertNotIn("expected.yaml", prompt)
        self.assertNotIn("human gold", prompt.lower())

    def test_review_invokes_provider_once_and_uses_coverage_job_id(self) -> None:
        provider = FakeProvider(staged_bundle())
        extractor = CoverageV02Extractor(
            "十二月，孙权为备攻合肥。",
            {},
            {},
            {},
            "fixture",
            provider,
        )
        result = extractor.review(staged_bundle())
        self.assertEqual(1, len(provider.prompts))
        self.assertEqual("src_001", result["source"]["temp_id"])
        self.assertEqual(
            "model-v0+coverage-v0.2", result["source"]["extraction"]["job_id"]
        )

    def test_object_counts_supports_ab_reporting(self) -> None:
        bundle = staged_bundle()
        bundle["entities"] = [{}, {}]
        bundle["events"] = [{}]
        self.assertEqual(
            {"entities": 2, "events": 1, "claims": 0, "warnings": 0},
            object_counts(bundle),
        )


if __name__ == "__main__":
    unittest.main()
