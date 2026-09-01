from __future__ import annotations

import unittest

from evaluator_v2 import evaluation_report_v2, match_claims_detailed, match_events


CONFIG = {
    "time": {
        "normalization": {
            "forbid_unverified_month_conversion": True,
            "forbid_unverified_day_conversion": True,
        }
    },
    "claim": {
        "predicates": {
            "allowed": ["outcome", "fought", "affected", "gained_territory"],
            "aliases": {"caused_deaths": "affected", "held": "gained_territory"},
        }
    },
}


def source() -> dict:
    return {"temp_id": "src_001", "kind": "source", "title": "三国志·魏书·武帝纪"}


def historical_time(month: int | None = None) -> dict:
    source_calendar = {
        "system": "chinese_lunisolar_regnal",
        "era": "建安",
        "era_year": 13,
    }
    if month is not None:
        source_calendar["month"] = month
    return {
        "original_text": "于是" if month is None else f"{month}月",
        "source_calendar": source_calendar,
        "normalized": {
            "calendar": "proleptic_gregorian",
            "year": 208,
            "precision": "year",
            "conversion_status": "year_only",
        },
    }


def entity(identity: str, name: str, entity_type: str = "person") -> dict:
    return {
        "temp_id": identity,
        "kind": "entity",
        "type": entity_type,
        "canonical_name": name,
        "mentions": [{"text": name}],
    }


def event(identity: str, title: str, event_type: str) -> dict:
    return {
        "temp_id": identity,
        "kind": "event",
        "type": event_type,
        "title": title,
        "time": historical_time(),
        "participants": [],
        "places": [],
    }


def claim(identity: str, subject: dict, predicate: str, evidence: str, obj: dict | None) -> dict:
    return {
        "temp_id": identity,
        "kind": "claim",
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "time": historical_time(),
        "evidence": {"text": evidence, "source_ref": "src_001", "locator": {}},
        "assessment": {"status": "unassessed"},
    }


class EvaluatorV2RefinementTests(unittest.TestCase):
    def test_epidemic_raw_title_matches_normalized_title(self) -> None:
        actual = {
            "source": source(),
            "entities": [],
            "events": [event("evt_001", "于是大疫，吏士多死者", "epidemic")],
            "claims": [],
        }
        expected = {
            "source": source(),
            "entities": [],
            "events": [event("evt_900", "曹操军发生大疫", "epidemic")],
            "claims": [],
        }
        matches, missing, additional = match_events(actual, expected)
        self.assertEqual(1, len(matches))
        self.assertEqual([], missing)
        self.assertEqual([], additional)

    def test_claim_literal_containment_matches_atomic_outcome(self) -> None:
        actual_event = event("evt_001", "公至赤壁，与备战，不利", "battle")
        expected_event = event("evt_900", "曹操与刘备在赤壁交战失利", "battle")
        event_matches, _, _ = match_events(actual={"events": [actual_event]}, expected={"events": [expected_event]}, threshold=0.45)
        actual = {
            "source": source(),
            "entities": [],
            "events": [actual_event],
            "claims": [
                claim(
                    "clm_001",
                    {"kind": "event_ref", "ref": "evt_001"},
                    "outcome",
                    "不利",
                    {"kind": "literal", "value": "不利"},
                )
            ],
        }
        expected = {
            "source": source(),
            "entities": [],
            "events": [expected_event],
            "claims": [
                claim(
                    "clm_900",
                    {"kind": "event_ref", "ref": "evt_900"},
                    "outcome",
                    "公至赤壁，与备战，不利。",
                    {"kind": "literal", "value": "曹操军不利"},
                )
            ],
        }
        result = match_claims_detailed(actual, expected, CONFIG, event_matches)
        self.assertEqual(1, result.matched)
        self.assertEqual(0, result.composite_matched)

    def test_composite_claim_coverage_can_cover_one_longer_gold_assertion(self) -> None:
        actual = {
            "source": source(),
            "entities": [entity("ent_001", "曹操"), entity("ent_002", "刘备")],
            "events": [],
            "claims": [
                claim(
                    "clm_001",
                    {"kind": "entity_ref", "ref": "ent_001"},
                    "fought",
                    "公至赤壁，与备战",
                    {"kind": "entity_ref", "ref": "ent_002"},
                ),
                claim(
                    "clm_002",
                    {"kind": "entity_ref", "ref": "ent_001"},
                    "outcome",
                    "不利",
                    {"kind": "literal", "value": "不利"},
                ),
            ],
        }
        expected = {
            "source": source(),
            "entities": [entity("ent_901", "曹操"), entity("ent_902", "刘备")],
            "events": [],
            "claims": [
                claim(
                    "clm_900",
                    {"kind": "entity_ref", "ref": "ent_901"},
                    "outcome",
                    "公至赤壁，与备战，不利",
                    {"kind": "literal", "value": "曹操军不利"},
                )
            ],
        }
        result = match_claims_detailed(actual, expected, CONFIG, [], threshold=0.95)
        self.assertEqual(1, result.matched)
        self.assertEqual(1, result.composite_matched)

    def test_entity_surface_containment_requires_same_type(self) -> None:
        raw = "备遂有江南诸郡。以文聘为江夏太守。"
        actual = {
            "source": source(),
            "entities": [
                entity("ent_001", "江南诸郡", "place"),
                entity("ent_002", "江夏太守", "office"),
            ],
            "events": [],
            "claims": [],
            "warnings": [],
        }
        expected = {
            "source": source(),
            "entities": [
                entity("ent_901", "江南", "place"),
                entity("ent_902", "江夏", "place"),
            ],
            "events": [],
            "claims": [],
        }
        report = evaluation_report_v2(actual, raw, CONFIG, [], expected, "model-v0", "test")
        entities = report["semantic_evaluation"]["entities"]
        self.assertEqual(0.5, entities["gold_recall"])
        self.assertEqual(["江夏"], entities["missing_gold"])
        self.assertEqual(["江夏太守"], entities["additional_output"])


if __name__ == "__main__":
    unittest.main()
