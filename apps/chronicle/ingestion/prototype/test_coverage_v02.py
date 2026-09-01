from __future__ import annotations

import copy
import json
import unittest

from coverage_v02 import (
    CoverageV02Extractor,
    audit_summary,
    build_coverage_prompt,
    coverage_unit_contexts,
    coverage_units,
    merge_coverage_additions,
    object_counts,
    parse_coverage_response,
)
from model_v0 import ModelV0Error


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
            "extraction": {"method": "model", "job_id": "model-v0"},
        },
        "entities": [],
        "events": [],
        "claims": [],
        "warnings": [],
    }


def empty_additions() -> dict:
    return {"entities": [], "events": [], "claims": [], "warnings": []}


def context_row(unit_id: str) -> dict:
    return {
        "unit_id": unit_id,
        "status": "context_only",
        "pass1_refs": [],
        "addition_refs": [],
        "claim_status": "not_applicable",
        "claim_refs": [],
        "claim_note": "chronology only; no factual assertion",
        "note": "chronology only",
    }


class CoverageV02Tests(unittest.TestCase):
    def test_coverage_units_and_source_month_context_are_deterministic(self) -> None:
        raw = "八月，表卒，屯襄阳。九月，公到新野。"
        self.assertEqual(
            [
                {"unit_id": "u001", "text": "八月"},
                {"unit_id": "u002", "text": "表卒"},
                {"unit_id": "u003", "text": "屯襄阳"},
                {"unit_id": "u004", "text": "九月"},
                {"unit_id": "u005", "text": "公到新野"},
            ],
            coverage_units(raw),
        )
        contexts = coverage_unit_contexts(raw)
        self.assertEqual(8, contexts["u003"]["source_month_hint"])
        self.assertEqual(9, contexts["u005"]["source_month_hint"])

    def test_prompt_requires_distinct_claim_coverage_and_source_month_hint(self) -> None:
        prompt = build_coverage_prompt(
            "十二月，孙权为备攻合肥。",
            {"chronology": {"normalized_year": 208}},
            {"claim": {"predicates": {"allowed": ["attacked"]}}},
            {"type": "object"},
            staged_bundle(),
        )
        self.assertIn("Event coverage and Claim coverage are DIFFERENT", prompt)
        self.assertIn("source_month_hint", prompt)
        self.assertIn('"source_month_hint": 12', prompt)
        self.assertIn("attacked", prompt)
        self.assertNotIn("expected.yaml", prompt)
        self.assertNotIn("human gold", prompt.lower())

    def test_audit_rejects_entity_only_overall_coverage(self) -> None:
        initial = staged_bundle()
        initial["entities"] = [{"temp_id": "ent_001"}]
        response = {
            "audit": [
                context_row("u001"),
                {
                    "unit_id": "u002",
                    "status": "covered",
                    "pass1_refs": ["ent_001"],
                    "addition_refs": [],
                    "claim_status": "not_applicable",
                    "claim_refs": [],
                    "claim_note": "no predicate",
                    "note": "entity exists",
                },
            ],
            **empty_additions(),
        }
        with self.assertRaises(ModelV0Error):
            parse_coverage_response(
                json.dumps(response, ensure_ascii=False),
                "十二月，孙权为备攻合肥。",
                initial,
            )

    def test_audit_rejects_claim_gap_without_new_claim(self) -> None:
        response = {
            "audit": [
                context_row("u001"),
                {
                    "unit_id": "u002",
                    "status": "gap",
                    "pass1_refs": [],
                    "addition_refs": ["evt_900"],
                    "claim_status": "gap",
                    "claim_refs": [],
                    "claim_note": "attack requires attacked Claim",
                    "note": "attack missing",
                },
            ],
            "entities": [],
            "events": [
                {
                    "temp_id": "evt_900",
                    "time": {
                        "source_calendar": {
                            "system": "chinese_lunisolar_regnal",
                            "month": 12,
                        }
                    },
                }
            ],
            "claims": [],
            "warnings": [],
        }
        with self.assertRaises(ModelV0Error):
            parse_coverage_response(
                json.dumps(response, ensure_ascii=False),
                "十二月，孙权为备攻合肥。",
                staged_bundle(),
            )

    def test_audit_rejects_wrong_inherited_source_month(self) -> None:
        response = {
            "audit": [
                context_row("u001"),
                {
                    "unit_id": "u002",
                    "status": "gap",
                    "pass1_refs": [],
                    "addition_refs": ["evt_900", "clm_900"],
                    "claim_status": "gap",
                    "claim_refs": ["clm_900"],
                    "claim_note": "stationing is representable by stationed_at",
                    "note": "missing stationing",
                },
            ],
            "entities": [],
            "events": [
                {
                    "temp_id": "evt_900",
                    "time": {
                        "source_calendar": {
                            "system": "chinese_lunisolar_regnal",
                            "month": 9,
                        }
                    },
                }
            ],
            "claims": [
                {
                    "temp_id": "clm_900",
                    "time": {
                        "source_calendar": {
                            "system": "chinese_lunisolar_regnal",
                            "month": 8,
                        }
                    },
                }
            ],
            "warnings": [],
        }
        with self.assertRaisesRegex(ModelV0Error, "expected 8, got 9"):
            parse_coverage_response(
                json.dumps(response, ensure_ascii=False),
                "八月，屯襄阳。",
                staged_bundle(),
            )

    def test_review_preserves_pass1_when_event_and_claim_are_covered(self) -> None:
        initial = staged_bundle()
        initial["events"] = [{"temp_id": "evt_001"}]
        initial["claims"] = [{"temp_id": "clm_001"}]
        patch = {
            "audit": [
                context_row("u001"),
                {
                    "unit_id": "u002",
                    "status": "covered",
                    "pass1_refs": ["evt_001", "clm_001"],
                    "addition_refs": [],
                    "claim_status": "covered",
                    "claim_refs": ["clm_001"],
                    "claim_note": "existing attacked Claim covers assertion",
                    "note": "existing Event and Claim cover attack",
                },
            ],
            **empty_additions(),
        }
        extractor = CoverageV02Extractor(
            "十二月，孙权为备攻合肥。", {}, {}, {}, "fixture", FakeProvider(patch)
        )
        result, stats = extractor.review(initial)
        self.assertEqual(initial, result)
        self.assertEqual("audit+claim-coverage+additions-only", stats["protocol"])
        self.assertEqual(
            {"covered": 1, "gap": 0, "not_applicable": 1},
            stats["audit"]["claim_status_counts"],
        )

    def test_merge_maps_duplicate_entity_and_keeps_existing_objects_immutable(self) -> None:
        initial = staged_bundle()
        initial["entities"] = [
            {
                "temp_id": "ent_001",
                "kind": "entity",
                "type": "person",
                "canonical_name": "孙权",
                "aliases": [],
                "mentions": [{"text": "孙权"}],
                "resolution": {"status": "unresolved"},
                "extraction": {"method": "model", "job_id": "model-v0"},
            }
        ]
        snapshot = copy.deepcopy(initial)
        additions = {
            "entities": [
                {
                    "temp_id": "ent_900",
                    "kind": "entity",
                    "type": "person",
                    "canonical_name": "孙权",
                    "aliases": [],
                    "mentions": [{"text": "孙权"}],
                    "resolution": {"status": "unresolved"},
                    "extraction": {"method": "model"},
                },
                {
                    "temp_id": "ent_901",
                    "kind": "entity",
                    "type": "place",
                    "canonical_name": "合肥",
                    "aliases": [],
                    "mentions": [{"text": "合肥"}],
                    "resolution": {"status": "unresolved"},
                    "extraction": {"method": "model"},
                },
            ],
            "events": [
                {
                    "temp_id": "evt_900",
                    "kind": "event",
                    "type": "military",
                    "title": "孙权攻合肥",
                    "time": None,
                    "participants": [{"entity_ref": "ent_900", "role": "attacker"}],
                    "places": ["ent_901"],
                    "extraction": {"method": "model"},
                }
            ],
            "claims": [
                {
                    "temp_id": "clm_900",
                    "kind": "claim",
                    "subject": {"kind": "entity_ref", "ref": "ent_900"},
                    "predicate": "attacked",
                    "object": {"kind": "entity_ref", "ref": "ent_901"},
                    "time": None,
                    "evidence": {
                        "text": "孙权为备攻合肥",
                        "source_ref": "src_777",
                        "locator": {},
                    },
                    "assessment": {"status": "unassessed"},
                    "extraction": {"method": "model"},
                }
            ],
            "warnings": [],
        }
        result, stats = merge_coverage_additions(initial, additions)
        self.assertEqual(snapshot["entities"][0], result["entities"][0])
        self.assertEqual("ent_001", result["events"][0]["participants"][0]["entity_ref"])
        self.assertEqual("ent_002", result["claims"][0]["object"]["ref"])
        self.assertEqual(1, stats["skipped_duplicates"]["entities"])
        self.assertEqual(1, stats["added"]["claims"])

    def test_merge_deduplicates_claim_alias_and_contained_evidence(self) -> None:
        initial = staged_bundle()
        initial["entities"] = [
            {"temp_id": "ent_001", "type": "person", "canonical_name": "刘备"},
            {"temp_id": "ent_002", "type": "place", "canonical_name": "荆州"},
        ]
        initial["claims"] = [
            {
                "temp_id": "clm_001",
                "subject": {"kind": "entity_ref", "ref": "ent_001"},
                "predicate": "held",
                "object": {"kind": "entity_ref", "ref": "ent_002"},
                "time": None,
                "evidence": {"text": "备遂有荆州、江南诸郡"},
            }
        ]
        additions = empty_additions()
        additions["claims"] = [
            {
                "temp_id": "clm_900",
                "subject": {"kind": "entity_ref", "ref": "ent_001"},
                "predicate": "gained_territory",
                "object": {"kind": "entity_ref", "ref": "ent_002"},
                "time": None,
                "evidence": {"text": "备遂有荆州"},
            }
        ]
        result, stats = merge_coverage_additions(
            initial,
            additions,
            {"claim": {"predicates": {"aliases": {"held": "gained_territory"}}}},
        )
        self.assertEqual(1, len(result["claims"]))
        self.assertEqual(1, stats["skipped_duplicates"]["claims"])

    def test_audit_summary_reports_claim_gaps(self) -> None:
        audit = [
            context_row("u001"),
            {
                "unit_id": "u002",
                "status": "gap",
                "claim_status": "gap",
            },
        ]
        summary = audit_summary(audit)
        self.assertEqual(["u002"], summary["gap_units"])
        self.assertEqual(["u002"], summary["claim_gap_units"])

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
