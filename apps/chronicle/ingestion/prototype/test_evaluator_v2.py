from __future__ import annotations

import unittest

from evaluator_v2 import evaluation_report_v2, hard_checks, match_claims, match_events


CONFIG = {
    "time": {
        "normalization": {
            "forbid_unverified_month_conversion": True,
            "forbid_unverified_day_conversion": True,
        }
    },
    "claim": {
        "predicates": {
            "allowed": [
                "held_office",
                "died",
                "succeeded",
                "surrendered_to",
                "outcome",
            ],
            "aliases": {
                "appointed_as": "held_office",
                "surrendered": "surrendered_to",
            },
        }
    },
}


def time(month: int = 8) -> dict:
    return {
        "original_text": "八月",
        "source_calendar": {
            "system": "chinese_lunisolar_regnal",
            "era": "建安",
            "era_year": 13,
            "month": month,
        },
        "normalized": {
            "calendar": "proleptic_gregorian",
            "year": 208,
            "precision": "year",
            "conversion_status": "year_only",
        },
    }


def source() -> dict:
    return {"temp_id": "src_001", "kind": "source", "title": "三国志·魏书·武帝纪"}


def entity(identity: str, name: str, entity_type: str = "person", mention: str | None = None) -> dict:
    return {
        "temp_id": identity,
        "kind": "entity",
        "type": entity_type,
        "canonical_name": name,
        "mentions": [{"text": mention or name}],
    }


def event(identity: str, title: str, event_type: str, participant: str, role: str = "subject") -> dict:
    return {
        "temp_id": identity,
        "kind": "event",
        "type": event_type,
        "title": title,
        "time": time(),
        "participants": [{"entity_ref": participant, "role": role}],
        "places": [],
    }


def claim(identity: str, subject: str, predicate: str, evidence: str) -> dict:
    return {
        "temp_id": identity,
        "kind": "claim",
        "subject": {"kind": "entity_ref", "ref": subject},
        "predicate": predicate,
        "object": None,
        "time": time(),
        "evidence": {"text": evidence, "source_ref": "src_001", "locator": {}},
        "assessment": {"status": "unassessed"},
    }


class EvaluatorV2Tests(unittest.TestCase):
    def test_event_matching_does_not_use_title_as_identity(self) -> None:
        actual = {
            "source": source(),
            "entities": [entity("ent_001", "刘表", mention="表")],
            "events": [event("evt_001", "表卒", "death", "ent_001")],
            "claims": [],
        }
        expected = {
            "source": source(),
            "entities": [entity("ent_900", "刘表", mention="表")],
            "events": [event("evt_900", "刘表去世", "death", "ent_900")],
            "claims": [],
        }
        matches, missing, additional = match_events(actual, expected)
        self.assertEqual(1, len(matches))
        self.assertEqual([], missing)
        self.assertEqual([], additional)

    def test_claim_matching_accepts_predicate_alias_and_evidence_span(self) -> None:
        actual = {
            "source": source(),
            "entities": [entity("ent_001", "刘表", mention="表")],
            "events": [],
            "claims": [claim("clm_001", "ent_001", "died", "表卒")],
        }
        expected = {
            "source": source(),
            "entities": [entity("ent_900", "刘表", mention="表")],
            "events": [],
            "claims": [claim("clm_900", "ent_900", "died", "八月，表卒")],
        }
        matched, missing, additional = match_claims(actual, expected, CONFIG, [])
        self.assertEqual(1, matched)
        self.assertEqual([], missing)
        self.assertEqual([], additional)

    def test_additional_source_grounded_entities_are_not_hard_failures(self) -> None:
        raw = "八月，表卒。刘璋遣兵给军。"
        bundle = {
            "source": source(),
            "entities": [
                entity("ent_001", "刘表", mention="表"),
                entity("ent_002", "刘璋"),
            ],
            "events": [],
            "claims": [],
        }
        checks = hard_checks(bundle, raw, CONFIG)
        self.assertEqual([], checks["grounding"])

    def test_hard_checks_detect_grounding_reference_precision_and_predicate(self) -> None:
        raw = "八月，表卒。"
        bad_time = time()
        bad_time["normalized"]["month"] = 8
        bundle = {
            "source": source(),
            "entities": [entity("ent_001", "刘表", mention="表")],
            "events": [
                {
                    "temp_id": "evt_001",
                    "kind": "event",
                    "type": "death",
                    "title": "表卒",
                    "time": bad_time,
                    "participants": [{"entity_ref": "ent_missing", "role": "subject"}],
                    "places": [],
                }
            ],
            "claims": [
                {
                    **claim("clm_001", "ent_001", "invented_predicate", "刘表病死"),
                    "assessment": {"status": "supported"},
                }
            ],
        }
        checks = hard_checks(bundle, raw, CONFIG)
        self.assertEqual(1, len(checks["grounding"]))
        self.assertEqual(1, len(checks["reference_integrity"]))
        self.assertEqual(1, len(checks["time_precision"]))
        self.assertEqual(1, len(checks["predicate_vocabulary"]))
        self.assertEqual(1, len(checks["initial_assessment"]))

    def test_report_uses_gold_recall_not_fake_precision(self) -> None:
        raw = "八月，表卒。刘璋遣兵给军。"
        actual = {
            "source": source(),
            "entities": [
                entity("ent_001", "刘表", mention="表"),
                entity("ent_002", "刘璋"),
            ],
            "events": [event("evt_001", "表卒", "death", "ent_001")],
            "claims": [claim("clm_001", "ent_001", "died", "表卒")],
            "warnings": [],
        }
        expected = {
            "source": source(),
            "entities": [entity("ent_900", "刘表", mention="表")],
            "events": [event("evt_900", "刘表去世", "death", "ent_900")],
            "claims": [claim("clm_900", "ent_900", "died", "八月，表卒")],
        }
        report = evaluation_report_v2(
            actual,
            raw,
            CONFIG,
            schema_errors=[],
            expected=expected,
            extractor="model-v0",
            provider="test",
        )
        self.assertTrue(report["hard_failures"]["passed"])
        self.assertEqual(1.0, report["semantic_evaluation"]["entities"]["gold_recall"])
        self.assertEqual(["刘璋"], report["semantic_evaluation"]["entities"]["additional_output"])
        self.assertNotIn("precision", report["semantic_evaluation"]["entities"])
        self.assertEqual(1.0, report["semantic_evaluation"]["events"]["gold_recall"])
        self.assertEqual(1.0, report["semantic_evaluation"]["claims"]["gold_recall"])


if __name__ == "__main__":
    unittest.main()
