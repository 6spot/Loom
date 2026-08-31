from __future__ import annotations

import json
import sys
import unittest

from model_v0 import (
    CommandModelProvider,
    ModelV0Error,
    ModelV0Extractor,
    build_model_prompt,
    compare_model_bundle,
    evaluation_report,
    normalize_model_bundle,
    parse_model_response,
)

RAW = "十三年春正月，公还邺。"
CONTEXT = {
    "schema": "chronicle.document-context",
    "version": "0.1",
    "source": {"title": "三国志·魏书·武帝纪"},
    "chronology": {"normalized_year": 208},
}
CONFIG = {"schema": "chronicle.ingestion", "version": "0.1"}
SCHEMA = {"type": "object"}

SAMPLE = {
    "schema_version": "0.1",
    "source": {
        "temp_id": "source-x",
        "kind": "source",
        "source_type": "book",
        "title": "三国志·魏书·武帝纪",
        "language": "lzh",
        "metadata": {},
        "extraction": {"method": "parser"},
    },
    "entities": [
        {
            "temp_id": "person-x",
            "kind": "entity",
            "type": "person",
            "canonical_name": "曹操",
            "aliases": [],
            "mentions": [{"text": "公", "contextual": True}],
            "resolution": {"status": "unresolved"},
            "extraction": {"method": "parser"},
        }
    ],
    "events": [
        {
            "temp_id": "event-x",
            "kind": "event",
            "type": "movement",
            "title": "曹操还邺",
            "time": None,
            "participants": [{"entity_ref": "person-x", "role": "actor"}],
            "places": [],
            "extraction": {"method": "parser"},
        }
    ],
    "claims": [
        {
            "temp_id": "claim-x",
            "kind": "claim",
            "subject": {"kind": "event_ref", "ref": "event-x"},
            "predicate": "occurred",
            "object": None,
            "time": None,
            "evidence": {"text": "公还邺", "source_ref": "source-x", "locator": {}},
            "assessment": {"status": "unassessed"},
            "extraction": {"method": "parser"},
        }
    ],
    "warnings": [],
}


class StubProvider:
    name = "stub"

    def __init__(self, response: str):
        self.response = response
        self.seen_prompt = None

    def complete(self, prompt: str) -> str:
        self.seen_prompt = prompt
        return self.response


class ModelV0Tests(unittest.TestCase):
    def test_prompt_is_closed_book_and_has_no_gold_input(self) -> None:
        prompt = build_model_prompt(RAW, CONTEXT, CONFIG, SCHEMA)
        self.assertIn(RAW, prompt)
        self.assertIn("closed book", prompt)
        self.assertIn("Do not add facts from prior historical knowledge", prompt)
        self.assertNotIn("expected.yaml", prompt)
        self.assertNotIn("SECRET_GOLD_SENTINEL", prompt)

    def test_command_provider_passes_prompt_on_stdin(self) -> None:
        provider = CommandModelProvider(
            [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read())"]
        )
        self.assertEqual("prompt payload", provider.complete("prompt payload"))

    def test_parse_accepts_plain_and_fenced_json(self) -> None:
        self.assertEqual({"a": 1}, parse_model_response('{"a": 1}'))
        self.assertEqual({"a": 1}, parse_model_response('```json\n{"a": 1}\n```'))
        with self.assertRaises(ModelV0Error):
            parse_model_response("[]")
        with self.assertRaises(ModelV0Error):
            parse_model_response("not-json")

    def test_extractor_normalizes_transport_ids_and_diagnostics(self) -> None:
        provider = StubProvider(json.dumps(SAMPLE, ensure_ascii=False))
        bundle = ModelV0Extractor(
            RAW, CONTEXT, CONFIG, SCHEMA, "fixture", provider
        ).extract()
        self.assertIsNotNone(provider.seen_prompt)
        self.assertEqual("src_001", bundle["source"]["temp_id"])
        self.assertEqual("ent_001", bundle["entities"][0]["temp_id"])
        self.assertEqual("evt_001", bundle["events"][0]["temp_id"])
        self.assertEqual(
            "ent_001", bundle["events"][0]["participants"][0]["entity_ref"]
        )
        self.assertEqual("evt_001", bundle["claims"][0]["subject"]["ref"])
        self.assertEqual("src_001", bundle["claims"][0]["evidence"]["source_ref"])
        self.assertEqual("model", bundle["claims"][0]["extraction"]["method"])
        self.assertIsNone(bundle["claims"][0]["extraction"]["confidence"])

    def test_model_comparison_ignores_temp_id_spelling(self) -> None:
        left = normalize_model_bundle(SAMPLE, "fixture")
        changed = json.loads(json.dumps(SAMPLE, ensure_ascii=False))
        changed["source"]["temp_id"] = "different-source"
        changed["entities"][0]["temp_id"] = "different-person"
        changed["events"][0]["temp_id"] = "different-event"
        changed["claims"][0]["temp_id"] = "different-claim"
        changed["events"][0]["participants"][0]["entity_ref"] = "different-person"
        changed["claims"][0]["subject"]["ref"] = "different-event"
        changed["claims"][0]["evidence"]["source_ref"] = "different-source"
        right = normalize_model_bundle(changed, "fixture")
        self.assertEqual([], compare_model_bundle(left, right))

    def test_evaluation_report_is_machine_readable(self) -> None:
        report = evaluation_report(
            SAMPLE, "model-v0", "stub", [], ["events: missing example"]
        )
        self.assertTrue(report["schema_validation"]["passed"])
        self.assertFalse(report["gold_comparison"]["passed"])
        self.assertEqual(1, report["gold_comparison"]["mismatch_count"])
        self.assertEqual(1, report["counts"]["events"])


if __name__ == "__main__":
    unittest.main()
