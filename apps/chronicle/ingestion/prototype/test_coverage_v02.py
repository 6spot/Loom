from __future__ import annotations

import copy
import json
import unittest

from coverage_v02 import (
    CoverageV02Extractor,
    build_coverage_prompt,
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


class CoverageV02Tests(unittest.TestCase):
    def test_coverage_units_are_deterministic_and_in_text_order(self) -> None:
        self.assertEqual(
            [
                {"unit_id": "u001", "text": "十二月"},
                {"unit_id": "u002", "text": "孙权为备攻合肥"},
            ],
            coverage_units("十二月，孙权为备攻合肥。"),
        )

    def test_prompt_contains_audit_units_and_no_reference_answer(self) -> None:
        prompt = build_coverage_prompt(
            "十二月，孙权为备攻合肥。",
            {"chronology": {"normalized_year": 208}},
            {"claim": {"predicates": {"allowed": ["attacked"]}}},
            {"type": "object"},
            staged_bundle(),
        )
        self.assertIn("十二月，孙权为备攻合肥。", prompt)
        self.assertIn("PASS-1 STAGED BUNDLE (IMMUTABLE)", prompt)
        self.assertIn("AUDIT UNITS (MACHINE-DERIVED, TEXTUAL ORDER)", prompt)
        self.assertIn("Entity presence alone NEVER", prompt)
        self.assertIn('"unit_id": "u001"', prompt)
        self.assertNotIn("expected.yaml", prompt)
        self.assertNotIn("human gold", prompt.lower())

    def test_audit_rejects_entity_only_covered_claim(self) -> None:
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
                "extraction": {"method": "model"},
            }
        ]
        response = {
            "audit": [
                {
                    "unit_id": "u001",
                    "status": "context_only",
                    "pass1_refs": [],
                    "addition_refs": [],
                    "note": "chronology",
                },
                {
                    "unit_id": "u002",
                    "status": "covered",
                    "pass1_refs": ["ent_001"],
                    "addition_refs": [],
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

    def test_review_invokes_provider_once_and_preserves_pass1_when_audited_covered(self) -> None:
        initial = staged_bundle()
        initial["events"] = [
            {
                "temp_id": "evt_001",
                "kind": "event",
                "type": "military",
                "title": "孙权攻合肥",
                "time": None,
                "participants": [],
                "places": [],
                "extraction": {"method": "model"},
            }
        ]
        patch = {
            "audit": [
                {
                    "unit_id": "u001",
                    "status": "context_only",
                    "pass1_refs": [],
                    "addition_refs": [],
                    "note": "month marker only",
                },
                {
                    "unit_id": "u002",
                    "status": "covered",
                    "pass1_refs": ["evt_001"],
                    "addition_refs": [],
                    "note": "existing event represents the attack",
                },
            ],
            **empty_additions(),
        }
        provider = FakeProvider(patch)
        extractor = CoverageV02Extractor(
            "十二月，孙权为备攻合肥。",
            {},
            {},
            {},
            "fixture",
            provider,
        )
        result, stats = extractor.review(initial)
        self.assertEqual(1, len(provider.prompts))
        self.assertEqual(initial, result)
        self.assertEqual("audit+additions-only", stats["protocol"])
        self.assertEqual(0, sum(stats["added"].values()))
        self.assertEqual(
            {"covered": 1, "gap": 0, "context_only": 1},
            stats["audit"]["status_counts"],
        )
        self.assertIsNotNone(extractor.last_response)

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
        initial_snapshot = copy.deepcopy(initial)
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

        self.assertEqual(initial_snapshot["source"], result["source"])
        self.assertEqual(initial_snapshot["entities"][0], result["entities"][0])
        self.assertEqual(2, len(result["entities"]))
        self.assertEqual("ent_002", result["entities"][1]["temp_id"])
        self.assertEqual("ent_001", result["events"][0]["participants"][0]["entity_ref"])
        self.assertEqual(["ent_002"], result["events"][0]["places"])
        self.assertEqual("ent_001", result["claims"][0]["subject"]["ref"])
        self.assertEqual("ent_002", result["claims"][0]["object"]["ref"])
        self.assertEqual(1, stats["skipped_duplicates"]["entities"])
        self.assertEqual(1, stats["added"]["entities"])
        self.assertEqual(1, stats["added"]["events"])
        self.assertEqual(1, stats["added"]["claims"])

    def test_merge_deduplicates_claim_alias_and_contained_evidence(self) -> None:
        initial = staged_bundle()
        initial["entities"] = [
            {
                "temp_id": "ent_001",
                "kind": "entity",
                "type": "person",
                "canonical_name": "刘备",
                "aliases": [],
                "mentions": [{"text": "备"}],
                "resolution": {"status": "unresolved"},
                "extraction": {"method": "model"},
            },
            {
                "temp_id": "ent_002",
                "kind": "entity",
                "type": "place",
                "canonical_name": "荆州",
                "aliases": [],
                "mentions": [{"text": "荆州"}],
                "resolution": {"status": "unresolved"},
                "extraction": {"method": "model"},
            },
        ]
        initial["claims"] = [
            {
                "temp_id": "clm_001",
                "kind": "claim",
                "subject": {"kind": "entity_ref", "ref": "ent_001"},
                "predicate": "held",
                "object": {"kind": "entity_ref", "ref": "ent_002"},
                "time": None,
                "evidence": {
                    "text": "备遂有荆州、江南诸郡",
                    "source_ref": "src_777",
                    "locator": {},
                },
                "assessment": {"status": "unassessed"},
                "extraction": {"method": "model"},
            }
        ]
        additions = empty_additions()
        additions["claims"] = [
            {
                "temp_id": "clm_900",
                "kind": "claim",
                "subject": {"kind": "entity_ref", "ref": "ent_001"},
                "predicate": "gained_territory",
                "object": {"kind": "entity_ref", "ref": "ent_002"},
                "time": None,
                "evidence": {
                    "text": "备遂有荆州",
                    "source_ref": "src_777",
                    "locator": {},
                },
                "assessment": {"status": "unassessed"},
                "extraction": {"method": "model"},
            }
        ]
        config = {
            "claim": {
                "predicates": {"aliases": {"held": "gained_territory"}}
            }
        }
        result, stats = merge_coverage_additions(initial, additions, config)
        self.assertEqual(1, len(result["claims"]))
        self.assertEqual(1, stats["skipped_duplicates"]["claims"])

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
