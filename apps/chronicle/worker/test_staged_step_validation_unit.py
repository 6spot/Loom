"""Semantic errors must stay in their owning staged node, before review."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
for path in (HERE, HERE.parent / "persistence"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import chapter_contract
import chapter_production as protocol
import person_state_contract
import staged_chapter
import staged_chapter_contract
from test_staged_chapter_contract_unit import fixture


class StagedStepValidationTests(unittest.TestCase):
    def setUp(self):
        self.request, self.candidate = fixture()
        self.runner = staged_chapter.Runner.__new__(staged_chapter.Runner)
        self.runner.request = self.request
        self.extraction = {key: copy.deepcopy(self.candidate[key]) for key in (
            "chapter_id", "bundle", "mentions", "record_sources", "person_states", "warnings")}
        self.extraction["person_states"].pop("unit_phases")
        self.linking = {
            "chapter_id": self.request["chapter_id"],
            "translation_links": [{key: value for key, value in block.items() if key != "text"}
                                  for block in self.candidate["translation"]["blocks"]],
            "reading": copy.deepcopy(self.candidate["reading"]),
            "unit_phases": copy.deepcopy(self.candidate["person_states"]["unit_phases"]),
        }
        self.data = {"translation": self.candidate["translation"], "extraction": self.extraction}

    def errors(self, step, value):
        parsed, errors = protocol.parse_step(step, json.dumps(value, ensure_ascii=False))
        self.assertEqual(errors, [], "this regression must pass the step's JSON schema")
        return self.runner._semantic_errors(step, parsed, self.data if step == "linking" else {})

    def test_partial_extraction_is_valid_only_as_a_step_not_as_an_accepted_chapter(self):
        original = copy.deepcopy(self.extraction)
        self.assertEqual(self.errors("extraction", self.extraction), [])
        self.assertEqual(self.errors("linking", self.linking), [])
        self.assertEqual(self.extraction, original)
        self.assertFalse(chapter_contract.validate_chapter_candidate(self.request, self.extraction)["passed"])
        self.assertFalse(person_state_contract.validate_person_state_candidate(self.request, self.extraction)["passed"])
        self.assertFalse(staged_chapter_contract.validate_staged_candidate(self.request, self.extraction)["passed"])
        candidate = copy.deepcopy(self.candidate)
        candidate["person_states"]["unit_phases"] = []
        self.assertFalse(staged_chapter_contract.validate_staged_candidate(self.request, candidate)["passed"])

    def test_extraction_reuses_identity_source_and_person_state_semantics(self):
        for kind, expected in (
            ("resolution", 'must be "unresolved"'),
            ("source", "no record_sources"),
            ("mention", "surface"),
            ("anchor", "quote"),
            ("subject", "person_ref"),
            ("chapter", "chapter_id drift"),
        ):
            value = copy.deepcopy(self.extraction)
            if kind == "resolution":
                value["bundle"]["entities"][0]["resolution"]["status"] = "new"
            elif kind == "source":
                value["record_sources"].pop(0)
            elif kind == "mention":
                value["mentions"][0]["surface"] = "孫策"
            elif kind == "anchor":
                value["record_sources"][0]["selections"][0]["quote"] = "史料沒有這句"
            elif kind == "subject":
                value["person_states"]["facts"][0]["person_ref"]["ref"] = "ent_003"
            else:
                value["chapter_id"] = "ch_" + "a" * 24
            with self.subTest(kind=kind):
                self.assertTrue(any(expected in error for error in self.errors("extraction", value)))

    def test_linking_checks_duplicate_units_source_quotes_and_time_before_review(self):
        for kind, expected in (("duplicate", "duplicate"), ("time", "events mode"), ("phase", "unknown phase")):
            value = copy.deepcopy(self.linking)
            if kind == "duplicate":
                value["reading"]["units"].append(copy.deepcopy(value["reading"]["units"][0]))
            elif kind == "time":
                value["reading"]["units"][0]["narrative_time"]["mode"] = "events"
            else:
                value["unit_phases"][0]["phase_refs"] = ["ph_099"]
            with self.subTest(kind=kind):
                self.assertTrue(any(expected in error for error in self.errors("linking", value)))

    def test_event_selector_uses_translation_while_its_evidence_uses_original(self):
        value = copy.deepcopy(self.linking)
        source = copy.deepcopy(self.extraction["record_sources"][2]["selections"])
        self.data["translation"] = copy.deepcopy(self.candidate["translation"])
        self.data["translation"]["blocks"][0]["text"] = "建安三年，孙策授予周瑜建威中郎将。"
        span = {"span_id": "es_001", "status": "unresolved", "target_ref": None,
                "candidate_refs": [], "relation": "uncertain", "source_selections": source,
                "selection": {"quote": "授予周瑜建威中郎将", "occurrence": 1}}
        value["reading"]["units"][0]["event_spans"] = [span]
        self.assertEqual(self.errors("linking", value), [])
        span["selection"]["quote"] = "策授瑜建威中郎將"
        errors = self.errors("linking", value)
        self.assertTrue(any(".selection" in error and "quote" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
