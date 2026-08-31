from __future__ import annotations

import json
import unittest

from contract_v0 import ContractV0Extractor, build_contract_prompt


class FakeProvider:
    name = "fake"

    def __init__(self, response: dict):
        self.response = json.dumps(response, ensure_ascii=False)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class ContractV0Tests(unittest.TestCase):
    def test_prompt_is_complete_contract_first_and_closed_book(self) -> None:
        prompt = build_contract_prompt(
            "十二月，孙权为备攻合肥。",
            {"chronology": {"normalized_year": 208}},
            {"claim": {"predicates": {"allowed": ["attacked"]}}},
            {"type": "object"},
        )
        self.assertIn("Read the entire SOURCE TEXT", prompt)
        self.assertIn("Extract the source comprehensively", prompt)
        self.assertIn("Create an Event for a distinct historical occurrence", prompt)
        self.assertIn("Create Claims for explicit factual assertions", prompt)
        self.assertNotIn("expected.yaml", prompt)
        self.assertNotIn("human gold", prompt.lower())
        self.assertNotIn("coverage audit", prompt.lower())

    def test_extractor_normalizes_transport_without_gold(self) -> None:
        response = {
            "schema_version": "0.1",
            "source": {
                "temp_id": "src_x",
                "kind": "source",
                "source_type": "book",
                "title": "test",
                "language": "lzh",
                "metadata": {},
            },
            "entities": [],
            "events": [],
            "claims": [],
            "warnings": [],
        }
        provider = FakeProvider(response)
        bundle = ContractV0Extractor("原文", {}, {}, {}, "fixture", provider).extract()
        self.assertEqual(1, len(provider.prompts))
        self.assertEqual("src_001", bundle["source"]["temp_id"])
        self.assertEqual("contract-v0", bundle["source"]["extraction"]["job_id"])


if __name__ == "__main__":
    unittest.main()
