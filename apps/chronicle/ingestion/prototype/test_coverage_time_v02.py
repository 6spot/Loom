from __future__ import annotations

import json
import unittest

from coverage_time_v02 import hydrate_missing_source_times


CONTEXT = {
    "chronology": {
        "default_era": "建安",
        "current_era_year": 13,
        "normalized_year": 208,
        "source_calendar": "chinese_lunisolar_regnal",
    }
}
RAW = "八月，表卒，其子琮代，屯襄阳，刘备屯樊。九月，公到新野。"


def response_with_claim(time):
    return {
        "audit": [
            {
                "unit_id": "u001",
                "status": "context_only",
                "pass1_refs": [],
                "addition_refs": [],
                "claim_status": "not_applicable",
                "claim_refs": [],
                "claim_note": "chronology",
                "note": "chronology",
            },
            {
                "unit_id": "u002",
                "status": "gap",
                "pass1_refs": [],
                "addition_refs": ["clm_017"],
                "claim_status": "gap",
                "claim_refs": ["clm_017"],
                "claim_note": "missing claim",
                "note": "missing assertion",
            },
            {
                "unit_id": "u003",
                "status": "gap",
                "pass1_refs": [],
                "addition_refs": ["clm_018"],
                "claim_status": "gap",
                "claim_refs": ["clm_018"],
                "claim_note": "missing claim",
                "note": "missing assertion",
            },
            {
                "unit_id": "u004",
                "status": "covered",
                "pass1_refs": ["evt_001"],
                "addition_refs": [],
                "claim_status": "not_applicable",
                "claim_refs": [],
                "claim_note": "fixture test placeholder",
                "note": "covered",
            },
            {
                "unit_id": "u005",
                "status": "covered",
                "pass1_refs": ["evt_002"],
                "addition_refs": [],
                "claim_status": "not_applicable",
                "claim_refs": [],
                "claim_note": "fixture test placeholder",
                "note": "covered",
            },
            {
                "unit_id": "u006",
                "status": "context_only",
                "pass1_refs": [],
                "addition_refs": [],
                "claim_status": "not_applicable",
                "claim_refs": [],
                "claim_note": "chronology",
                "note": "chronology",
            },
            {
                "unit_id": "u007",
                "status": "covered",
                "pass1_refs": ["evt_003"],
                "addition_refs": [],
                "claim_status": "not_applicable",
                "claim_refs": [],
                "claim_note": "fixture test placeholder",
                "note": "covered",
            },
        ],
        "entities": [],
        "events": [],
        "claims": [
            {"temp_id": "clm_017", "time": time},
            {"temp_id": "clm_018", "time": None},
        ],
        "warnings": [],
    }


class CoverageTimeV02Tests(unittest.TestCase):
    def test_missing_claim_time_is_hydrated_from_source_month(self) -> None:
        value = response_with_claim(None)
        text, hydrated = hydrate_missing_source_times(
            json.dumps(value, ensure_ascii=False), RAW, CONTEXT
        )
        result = json.loads(text)
        claim = result["claims"][0]
        self.assertIn("clm_017", hydrated)
        self.assertEqual(8, claim["time"]["source_calendar"]["month"])
        self.assertEqual("建安", claim["time"]["source_calendar"]["era"])
        self.assertEqual(13, claim["time"]["source_calendar"]["era_year"])
        self.assertEqual(208, claim["time"]["normalized"]["year"])
        self.assertIsNone(claim["time"]["normalized"]["month"])
        self.assertIsNone(claim["time"]["normalized"]["day"])
        self.assertEqual("year_only", claim["time"]["normalized"]["conversion_status"])

    def test_inherited_month_is_recorded_as_inherited(self) -> None:
        value = response_with_claim(None)
        text, _ = hydrate_missing_source_times(
            json.dumps(value, ensure_ascii=False), RAW, CONTEXT
        )
        result = json.loads(text)
        inherited = result["claims"][1]["time"]["source_calendar"]["inherited_fields"]
        self.assertIn("month", inherited)
        self.assertEqual(8, result["claims"][1]["time"]["source_calendar"]["month"])

    def test_conflicting_model_month_is_not_silently_corrected(self) -> None:
        wrong_time = {
            "original_text": "九月",
            "source_calendar": {
                "system": "chinese_lunisolar_regnal",
                "era": "建安",
                "era_year": 13,
                "month": 9,
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
        value = response_with_claim(wrong_time)
        text, hydrated = hydrate_missing_source_times(
            json.dumps(value, ensure_ascii=False), RAW, CONTEXT
        )
        result = json.loads(text)
        self.assertNotIn("clm_017", hydrated)
        self.assertEqual(9, result["claims"][0]["time"]["source_calendar"]["month"])


if __name__ == "__main__":
    unittest.main()
