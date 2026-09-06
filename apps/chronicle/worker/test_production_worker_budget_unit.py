"""Regressions for the production worker's unified model-input budget."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
for path in (HERE, PERSISTENCE):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

import production_worker as P  # noqa: E402


class ProductionWorkerBudgetTests(unittest.TestCase):
    def test_default_budget_is_shared_by_segmentation_and_extraction(self) -> None:
        segmentation_config, extraction_config = P.production_configs({})

        self.assertEqual(
            P.DEFAULT_MODEL_INPUT_BUDGET_CHARS,
            segmentation_config.max_input_chars,
        )
        self.assertEqual(
            segmentation_config.max_input_chars,
            extraction_config.max_prompt_chars,
        )
        self.assertGreater(segmentation_config.reserved_prompt_chars, 1500)

    def test_prompt_template_growth_automatically_increases_reserve(self) -> None:
        baseline = P.measured_prompt_reserve_chars()
        original = P.worker.extraction.build_extraction_prompt

        def grown_prompt(**kwargs):
            return original(**kwargs) + ("x" * 777)

        with mock.patch.object(
            P.worker.extraction,
            "build_extraction_prompt",
            side_effect=grown_prompt,
        ):
            grown = P.measured_prompt_reserve_chars()

        self.assertEqual(baseline + 777, grown)

    def test_r11_style_second_chunk_prompt_over_old_8k_is_accepted_by_new_budget(self) -> None:
        segmentation_config, extraction_config = P.production_configs({})
        context = P.worker.segmentation.initial_context()
        context["recent_events"] = [
            {
                "text": "前文承接" + ("甲" * 3000),
                "source_chunk": 0,
            }
        ]
        context["active_entities"] = [
            {
                "text": "劉備",
                "first_seen_chunk": 0,
                "last_seen_chunk": 0,
                "count": 1,
            }
        ]
        chunk_text = "建安十三年，先主據樊。" + ("乙" * 1800)
        prompt = P.worker.extraction.build_extraction_prompt(
            chunk_text=chunk_text,
            section={"label": "全文", "kind": "document", "section_index": 0},
            document={"title": "三國志·蜀書·先主傳", "verified_normalized_year": 208},
            context_input=context,
            boundary_head=chunk_text[:200],
            boundary_tail=chunk_text[-200:],
        )

        self.assertGreater(len(prompt), 8000)
        self.assertLessEqual(len(prompt), extraction_config.max_prompt_chars)
        # The segmentation side uses the same authority and has enough room
        # to trim forwarded ContextState before extraction's final hard gate.
        self.assertEqual(
            segmentation_config.max_input_chars,
            extraction_config.max_prompt_chars,
        )

    def test_too_small_deployment_budget_fails_closed_with_clear_error(self) -> None:
        with self.assertRaisesRegex(
            P.PersistenceError,
            "too small for the current Chronicle prompt contract",
        ):
            P.production_configs({"CHRONICLE_MODEL_INPUT_BUDGET_CHARS": "4096"})

    def test_invalid_budget_environment_is_rejected(self) -> None:
        for value in ("0", "-1", "not-an-int"):
            with self.subTest(value=value):
                with self.assertRaises(P.PersistenceError):
                    P.model_input_budget_chars(
                        {"CHRONICLE_MODEL_INPUT_BUDGET_CHARS": value}
                    )


if __name__ == "__main__":
    unittest.main()
