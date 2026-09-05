"""Regressions for schema-shape drift exposed by the C1-T17 R8 live run."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import extraction as X  # noqa: E402
from test_extraction_unit import (  # noqa: E402
    ALLOWED_PREDICATES,
    CHUNK_0,
    FakeProvider,
    context_input,
    document,
    make_request,
    valid_bundle,
)


class R8ContractPromptTests(unittest.TestCase):
    def test_initial_prompt_names_canonical_shape_and_output_schema_version(self) -> None:
        request = make_request()
        prompt = request["prompt"]
        self.assertEqual("c1t6-prompt-v3", request["request_meta"]["prompt_version"])
        self.assertIn('Output schema_version MUST be "0.1"', prompt)
        self.assertIn('kind:"source"', prompt)
        self.assertIn("temp_id only", prompt)
        self.assertIn("entity_ref", prompt)
        self.assertIn("Do NOT put `claims` inside events", prompt)
        self.assertIn("Do NOT use singular `place`", prompt)
        self.assertIn("SECTION/DOCUMENT/CONTEXT are input metadata only", prompt)
        self.assertNotIn("chunk-extraction contract-v0.2", prompt)
        self.assertLessEqual(len(prompt), X.ExtractionConfig().max_prompt_chars)

    def test_r8_style_schema_drift_gets_bounded_shape_aware_correction(self) -> None:
        config = X.ExtractionConfig(max_repair_attempts=1)
        bad_events = []
        for index in range(24):
            bad_events.append(
                {
                    "id": f"evt_{index + 1:03d}",
                    "type": "campaign_and_departure",
                    "participants": [{"ref": "ent_001", "role": "actor"}],
                    "place": {"ref": "ent_002"},
                    "claims": [f"clm_{index + 1:03d}"],
                }
            )
        bad = {
            "schema_version": "0.2",
            "source": {
                "id": "src_001",
                "kind": "document",
                "title": "三国志·蜀书·先主传",
                "label": "全文",
                "section_index": 0,
            },
            "entities": [
                {
                    "id": "ent_001",
                    "type": "person",
                    "name": "劉表",
                }
            ],
            "events": bad_events,
            "claims": [],
            "warnings": [{"type": "schema_guess", "message": "guessed shape"}],
        }
        good = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        provider = FakeProvider(
            [json.dumps(bad, ensure_ascii=False), json.dumps(good, ensure_ascii=False)]
        )

        result = X.extract_chunk(
            provider,
            make_request(config=config),
            chunk_text=CHUNK_0,
            context_input=context_input(),
            section_label="全文",
            document=document(),
            schema=None,
            allowed_predicates=ALLOWED_PREDICATES,
            config=config,
        )

        self.assertTrue(result["accepted"], result["error"])
        self.assertEqual(2, len(provider.prompts))
        repair = provider.prompts[1]
        self.assertLessEqual(len(repair), config.max_prompt_chars)
        self.assertIn("CANONICAL BUNDLE SHAPE", repair)
        self.assertIn("VALIDATION DIAGNOSTICS", repair)
        self.assertIn("events/*", repair)
        self.assertIn("entity_ref", repair)
        self.assertIn("schema_version", repair)
        self.assertNotIn("events/23", repair)

    def test_compact_diagnostics_preserve_full_validation_history(self) -> None:
        config = X.ExtractionConfig(max_repair_attempts=1)
        bad = valid_bundle(CHUNK_0, "刘表去世", time_original="建安十三年")
        for index in range(80):
            bad["events"].append(copy.deepcopy(bad["events"][0]))
            bad["events"][-1]["id"] = f"evt_{index + 100:03d}"
            bad["events"][-1].pop("temp_id", None)
            bad["events"][-1]["participants"] = [{"ref": "ent_001", "role": "x"}]
        good = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        provider = FakeProvider(
            [json.dumps(bad, ensure_ascii=False), json.dumps(good, ensure_ascii=False)]
        )

        result = X.extract_chunk(
            provider,
            make_request(config=config),
            chunk_text=CHUNK_0,
            context_input=context_input(),
            section_label="全文",
            document=document(),
            schema=None,
            allowed_predicates=ALLOWED_PREDICATES,
            config=config,
        )

        self.assertTrue(result["accepted"], result["error"])
        first = result["attempts"][0]
        self.assertGreater(first["validation"]["count"], 80)
        self.assertLessEqual(len(provider.prompts[1]), config.max_prompt_chars)
        self.assertIn("additional/repeated validator errors", provider.prompts[1])


if __name__ == "__main__":
    unittest.main()
