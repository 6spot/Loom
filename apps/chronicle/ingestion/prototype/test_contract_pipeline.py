from __future__ import annotations

import json
import unittest

from model_v0 import ModelV0Error
from repair_v0 import apply_repair_patch, build_repair_prompt, repair_once
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


def entity(temp_id: str, name: str) -> dict:
    return {
        "temp_id": temp_id,
        "kind": "entity",
        "type": "person",
        "canonical_name": name,
        "aliases": [],
        "mentions": [{"text": name}],
        "resolution": {"status": "unresolved"},
        "extraction": {"method": "model", "job_id": "contract-v0.2"},
    }


def event(temp_id: str, event_type: str = "movement") -> dict:
    return {
        "temp_id": temp_id,
        "kind": "event",
        "type": event_type,
        "title": "刘备屯樊",
        "time": None,
        "participants": [],
        "places": [],
        "extraction": {"method": "model", "job_id": "contract-v0.2"},
    }


class ContractPipelineTests(unittest.TestCase):
    def test_source_calendar_rejects_declared_month_conflict(self) -> None:
        bundle = base_bundle()
        bundle["events"] = [event("evt_001")]
        bundle["events"][0]["time"] = traditional_time(9)
        errors = source_calendar_consistency(
            bundle, "八月，表卒，其子琮代，屯襄阳，刘备屯樊。九月，公到新野。"
        )
        self.assertEqual(1, len(errors))
        self.assertIn("expected 8, got 9", errors[0])

    def test_source_calendar_does_not_require_optional_time(self) -> None:
        bundle = base_bundle()
        bundle["events"] = [event("evt_001")]
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

    def test_repair_prompt_is_patch_only_and_validator_driven(self) -> None:
        prompt = build_repair_prompt(
            "八月，刘备屯樊。",
            {"chronology": {"normalized_year": 208}},
            {"time": {}},
            {"type": "object"},
            base_bundle(),
            ["source_calendar_consistency: evt_001 expected 8, got 9"],
        )
        self.assertIn("Correct ONLY", prompt)
        self.assertIn("Return a minimal repair patch only", prompt)
        self.assertIn("Never delete an existing Source, Entity, Event, or Claim", prompt)
        self.assertIn("VALIDATION ERRORS", prompt)
        self.assertIn("expected 8, got 9", prompt)
        self.assertNotIn("expected.yaml", prompt)
        self.assertNotIn("semantic_evaluation", prompt)

    def test_patch_replaces_one_record_without_dropping_others(self) -> None:
        bundle = base_bundle()
        bundle["entities"] = [entity("ent_001", "刘备"), entity("ent_002", "曹操")]
        bundle["events"] = [event("evt_001", "other"), event("evt_002", "movement")]
        corrected = event("evt_001", "movement")
        patch = {
            "replace": [
                {"collection": "events", "temp_id": "evt_001", "record": corrected}
            ],
            "add": {"entities": [], "events": [], "claims": [], "warnings": []},
            "remove_warning_messages": [],
        }
        repaired, stats = apply_repair_patch(bundle, patch)
        self.assertEqual(2, len(repaired["entities"]))
        self.assertEqual(2, len(repaired["events"]))
        self.assertEqual("movement", repaired["events"][0]["type"])
        self.assertEqual("evt_002", repaired["events"][1]["temp_id"])
        self.assertEqual(1, stats["replaced"]["events"])

    def test_patch_can_add_missing_entity_and_remove_stale_warning(self) -> None:
        bundle = base_bundle()
        bundle["warnings"] = [
            {
                "type": "ambiguous_resolution",
                "severity": "warning",
                "message": "夏口未建立实体",
                "refs": [],
            }
        ]
        added_entity = entity("ent_001", "夏口")
        added_entity["type"] = "place"
        patch = {
            "replace": [],
            "add": {
                "entities": [added_entity],
                "events": [],
                "claims": [],
                "warnings": [],
            },
            "remove_warning_messages": ["夏口未建立实体"],
        }
        repaired, stats = apply_repair_patch(bundle, patch)
        self.assertEqual(1, len(repaired["entities"]))
        self.assertEqual([], repaired["warnings"])
        self.assertEqual(1, stats["added"]["entities"])
        self.assertEqual(1, stats["removed_warnings"])

    def test_patch_rejects_reused_identity(self) -> None:
        bundle = base_bundle()
        bundle["entities"] = [entity("ent_001", "刘备")]
        patch = {
            "replace": [],
            "add": {
                "entities": [entity("ent_001", "曹操")],
                "events": [],
                "claims": [],
                "warnings": [],
            },
            "remove_warning_messages": [],
        }
        with self.assertRaises(ModelV0Error):
            apply_repair_patch(bundle, patch)

    def test_repair_once_applies_patch_not_full_bundle(self) -> None:
        bundle = base_bundle()
        bundle["entities"] = [entity("ent_001", "刘备")]
        bundle["events"] = [event("evt_001", "other"), event("evt_002", "movement")]
        response = {
            "replace": [
                {
                    "collection": "events",
                    "temp_id": "evt_001",
                    "record": event("evt_001", "movement"),
                }
            ],
            "add": {"entities": [], "events": [], "claims": [], "warnings": []},
            "remove_warning_messages": [],
        }
        provider = FakeProvider(response)
        repaired, _raw, stats = repair_once(
            provider,
            "原文",
            {},
            {},
            {"type": "object"},
            bundle,
            ["schema_validation: example"],
            "fixture",
        )
        self.assertEqual(1, len(provider.prompts))
        self.assertEqual(1, len(repaired["entities"]))
        self.assertEqual(2, len(repaired["events"]))
        self.assertEqual("movement", repaired["events"][0]["type"])
        self.assertEqual("patch-only-v0.2", stats["protocol"])


if __name__ == "__main__":
    unittest.main()
