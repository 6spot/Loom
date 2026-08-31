from __future__ import annotations

import json
import unittest

from repair_v0 import build_repair_prompt, repair_once
from validator_v0 import source_calendar_consistency, validation_report


class FakeProvider:
    name = "fake"

    def __init__(self, response: dict):
        self.response = json.dumps(response, ensure_ascii=False)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def base_bundle() -> dict:
    return {
        "schema_version": "0.1",
        "source": {
            "temp_id": "src_001",
            "kind": "source",
            "source_type": "book",
            "title": "test",
            "language": "lzh",
            "metadata": {},
            "extraction": {"method": "model", "job_id": "contract-v0.2"},
        },
        "entities": [],
        "events": [],
        "claims": [],
        "warnings": [],
    }


def traditional_time(month: int) -> dict:
    return {
        "original_text": f"{month}月",
        "source_calendar": {
            "system": "chinese_lunisolar_regnal",
            "era": "建安",
            "era_year": 13,
            "month": month,
            "season": None,
            "inherited_fields": ["era", "era_year"],
        },
        "normalized": {
            "calendar": "proleptic_gregorian",
            "year": 208,
            "month": None,
            "day": None,
            "precision": "year",
            "conversion_status": "year_only",
            "approximate": False,
        },
    }


class ContractPipelineTests(unittest.TestCase):
    def test_source_calendar_rejects_declared_month_conflict(self) -> None:
        bundle = base_bundle()
        bundle["events"] = [
            {
                "temp_id": "evt_001",
                "kind": "event",
                "type": "movement",
                "title": "刘备屯樊",
                "time": traditional_time(9),
                "participants": [],
                "places": [],
                "extraction": {"method": "model", "job_id": "contract-v0.2"},
            }
        ]
        errors = source_calendar_consistency(
            bundle, "八月，表卒，其子琮代，屯襄阳，刘备屯樊。九月，公到新野。"
        )
        self.assertEqual(1, len(errors))
        self.assertIn("expected 8, got 9", errors[0])

    def test_source_calendar_does_not_require_optional_time(self) -> None:
        bundle = base_bundle()
        bundle["events"] = [
            {
                "temp_id": "evt_001",
                "kind": "event",
                "type": "movement",
                "title": "刘备屯樊",
                "time": None,
                "participants": [],
                "places": [],
                "extraction": {"method": "model", "job_id": "contract-v0.2"},
            }
        ]
        self.assertEqual(
            [],
            source_calendar_consistency(
                bundle, "八月，表卒，其子琮代，屯襄阳，刘备屯樊。九月，公到新野。"
            ),
        )

    def test_validation_report_has_no_semantic_gold_layer(self) -> None:
        report = validation_report(base_bundle(), "原文", {}, schema_errors=[])
        self.assertEqual("chronicle.ingestion-validation", report["schema"])
        self.assertNotIn("semantic_evaluation", report)
        self.assertNotIn("gold", json.dumps(report).lower())

    def test_repair_prompt_contains_only_validator_driven_task(self) -> None:
        prompt = build_repair_prompt(
            "八月，刘备屯樊。",
            {"chronology": {"normalized_year": 208}},
            {"time": {}},
            {"type": "object"},
            base_bundle(),
            ["source_calendar_consistency: evt_001 expected 8, got 9"],
        )
        self.assertIn("Correct ONLY", prompt)
        self.assertIn("VALIDATION ERRORS", prompt)
        self.assertIn("expected 8, got 9", prompt)
        self.assertIn("smallest changes", prompt)
        self.assertIn("Warnings in the returned bundle must describe the corrected final bundle", prompt)
        self.assertNotIn("expected.yaml", prompt)
        self.assertNotIn("semantic_evaluation", prompt)

    def test_repair_once_returns_normalized_complete_bundle(self) -> None:
        response = base_bundle()
        response["source"]["temp_id"] = "src_900"
        provider = FakeProvider(response)
        repaired, _raw = repair_once(
            provider,
            "原文",
            {},
            {},
            {"type": "object"},
            base_bundle(),
            ["schema_validation: example"],
            "fixture",
        )
        self.assertEqual(1, len(provider.prompts))
        self.assertEqual("src_001", repaired["source"]["temp_id"])
        self.assertEqual("contract-v0.2+repair-v0", repaired["source"]["extraction"]["job_id"])


if __name__ == "__main__":
    unittest.main()
