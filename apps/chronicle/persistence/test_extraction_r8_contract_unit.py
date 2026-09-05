"""Regressions for schema-shape drift exposed by the C1-T17 R8 live run."""

from __future__ import annotations

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


def r8_style_bad_bundle(event_count: int = 24) -> dict:
    """Return the compact wrong shape observed in R8, below response guard."""
    bad_events = []
    for index in range(event_count):
        bad_events.append(
            {
                "id": f"evt_{index + 1:03d}",
                "type": "campaign_and_departure",
                "participants": [{"ref": "ent_001", "role": "actor"}],
                "place": {"ref": "ent_002"},
                "claims": [f"clm_{index + 1:03d}"],
            }
        )
    return {
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

    def _run_r8_drift(self) -> tuple[dict, FakeProvider]:
        config = X.ExtractionConfig(max_repair_attempts=1)
        bad = r8_style_bad_bundle()
        bad_raw = json.dumps(bad, ensure_ascii=False)
        self.assertLess(len(bad_raw), config.max_response_chars)
        good = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        provider = FakeProvider(
            [bad_raw, json.dumps(good, ensure_ascii=False)]
        )
        result = X.extract_chunk(
            provider,
            make_request(config=config),
            chunk_text=CHUNK_0,
            context_input=context_input(),
            section_label="全文",
            document=document(),
            schema=X.canonical_schema(),
            allowed_predicates=ALLOWED_PREDICATES,
            config=config,
        )
        return result, provider

    def test_r8_style_schema_drift_gets_bounded_shape_aware_correction(self) -> None:
        result, provider = self._run_r8_drift()

        self.assertTrue(result["accepted"], result["error"])
        self.assertEqual(2, len(provider.prompts))
        repair = provider.prompts[1]
        self.assertLessEqual(len(repair), X.ExtractionConfig().max_prompt_chars)
        self.assertIn("CANONICAL BUNDLE SHAPE", repair)
        self.assertIn("VALIDATION DIAGNOSTICS", repair)
        self.assertIn("events/*", repair)
        self.assertIn("entity_ref", repair)
        self.assertIn("schema_version", repair)
        self.assertNotIn("events/23", repair)

    def test_compact_diagnostics_preserve_full_validation_history(self) -> None:
        result, provider = self._run_r8_drift()

        self.assertTrue(result["accepted"], result["error"])
        first = result["attempts"][0]
        self.assertIsNotNone(first["validation"])
        self.assertGreater(first["validation"]["count"], 100)
        # Full deterministic validation remains in history; only the re-ask is
        # summarized/deduplicated to protect the fixed 8K model-input budget.
        full_errors = X.flatten_validation_errors(first["validation"])
        self.assertGreater(len(full_errors), 100)
        repair = provider.prompts[1]
        self.assertLessEqual(len(repair), X.ExtractionConfig().max_prompt_chars)
        self.assertIn("additional/repeated validator errors", repair)
        self.assertLess(repair.count("events/*"), 20)


if __name__ == "__main__":
    unittest.main()
