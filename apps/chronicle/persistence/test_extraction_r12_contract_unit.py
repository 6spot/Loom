"""Regressions for correction expansion exposed by the C1-T17 R12 live run."""

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
    extraction_meta,
    make_request,
    valid_bundle,
)


class R12CorrectionContractTests(unittest.TestCase):
    def _extract(self, first: dict, second: dict) -> tuple[dict, FakeProvider]:
        provider = FakeProvider(
            [json.dumps(first, ensure_ascii=False), json.dumps(second, ensure_ascii=False)]
        )
        config = X.ExtractionConfig(max_repair_attempts=1)
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

    def test_grounding_time_repair_prompt_is_monotonic_and_prefers_null(self) -> None:
        bad = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十四年")
        good = copy.deepcopy(bad)
        good["events"][0]["time"] = None
        good["claims"][0]["time"] = None

        result, provider = self._extract(bad, good)

        self.assertTrue(result["accepted"], result["error"])
        self.assertEqual(2, len(provider.prompts))
        repair = provider.prompts[1]
        self.assertIn("MONOTONIC REPAIR RULES", repair)
        self.assertIn("NOT a fresh extraction pass", repair)
        self.assertIn("set that event/claim time to null", repair)
        self.assertIn("Do NOT introduce new Entity/Event/Claim records", repair)
        self.assertIn("建安十四年", repair)

    def test_shape_valid_local_repair_rejects_new_temp_ids(self) -> None:
        bad = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十四年")
        expanded = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        expanded["entities"].append(
            {
                "temp_id": "ent_002",
                "kind": "entity",
                "type": "person",
                "canonical_name": "曹操",
                "aliases": [],
                "mentions": [{"text": "曹操"}],
                "resolution": {"status": "unresolved"},
                "extraction": extraction_meta(),
            }
        )

        result, _provider = self._extract(bad, expanded)

        self.assertFalse(result["accepted"])
        self.assertEqual(2, len(result["attempts"]))
        second = result["attempts"][1]
        self.assertIsNone(second["validation"])
        self.assertIn("repair policy", second["parse_error"])
        self.assertIn("ent_002", second["parse_error"])
        self.assertIn("correction repair expanded entities", result["error"])

    def test_shape_drift_is_not_blocked_by_monotonic_guard(self) -> None:
        bad = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        bad["schema_version"] = "0.2"
        bad["entities"][0]["id"] = bad["entities"][0].pop("temp_id")
        repaired = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        repaired["entities"].append(
            {
                "temp_id": "ent_002",
                "kind": "entity",
                "type": "person",
                "canonical_name": "曹操",
                "aliases": [],
                "mentions": [{"text": "曹操"}],
                "resolution": {"status": "unresolved"},
                "extraction": extraction_meta(),
            }
        )

        result, _provider = self._extract(bad, repaired)

        self.assertTrue(result["accepted"], result["error"])


if __name__ == "__main__":
    unittest.main()
