"""Live-limit regressions for Chronicle C1-T6 extraction.

These cover failures exposed by the C1-T17 real-machine gate without weakening
schema, grounding, or authority validation: a realistic model response may be
larger than the original 16K character guard, while oversized or correction
requests must remain bounded and fail closed.
"""

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


class ExtractionLiveLimitTests(unittest.TestCase):
    def _run(self, provider: FakeProvider, *, config: X.ExtractionConfig):
        return X.extract_chunk(
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

    def _near_budget_request(
        self, config: X.ExtractionConfig
    ) -> tuple[dict, dict]:
        """Return a valid initial request close enough to 8K to expose R7."""
        best: tuple[dict, dict] | None = None
        for padding in range(256, 6000, 128):
            ctx = context_input()
            ctx["recent_events"] = [
                {
                    "title": "bounded prior event",
                    "summary": "x" * padding,
                    "source_chunk": 0,
                }
            ]
            try:
                request = make_request(config=config, context_input=ctx)
            except X.PersistenceError:
                break
            best = (ctx, request)
        self.assertIsNotNone(best)
        assert best is not None
        self.assertGreater(
            best[1]["request_meta"]["prompt_chars"],
            config.max_prompt_chars - 500,
        )
        self.assertLessEqual(
            best[1]["request_meta"]["prompt_chars"], config.max_prompt_chars
        )
        return best

    def test_default_response_guard_accepts_r6_observed_size(self) -> None:
        self.assertEqual(32768, X.ExtractionConfig().max_response_chars)
        self.assertGreater(X.ExtractionConfig().max_response_chars, 26706)

    def test_over_budget_response_gets_one_bounded_compact_reask(self) -> None:
        config = X.ExtractionConfig(max_repair_attempts=1)
        good = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        provider = FakeProvider(
            ["x" * (config.max_response_chars + 1), json.dumps(good, ensure_ascii=False)]
        )

        result = self._run(provider, config=config)

        self.assertTrue(result["accepted"], result["error"])
        self.assertEqual(2, len(provider.prompts))
        self.assertLessEqual(len(provider.prompts[1]), config.max_prompt_chars)
        self.assertIn("exceeded the bounded response budget", provider.prompts[1])

    def test_large_invalid_candidate_uses_bounded_candidate_omission_fallback(self) -> None:
        config = X.ExtractionConfig(max_repair_attempts=1)
        bad = valid_bundle(CHUNK_0, "刘表去世", time_original="建安十三年")
        bad["warnings"] = [
            {
                "type": "ontology_gap",
                "severity": "warning",
                "message": "x" * 12000,
                "refs": [],
            }
        ]
        bad_raw = json.dumps(bad, ensure_ascii=False)
        self.assertLess(len(bad_raw), config.max_response_chars)
        self.assertGreater(len(bad_raw), config.max_prompt_chars)
        good = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        provider = FakeProvider([bad_raw, json.dumps(good, ensure_ascii=False)])

        result = self._run(provider, config=config)

        self.assertTrue(result["accepted"], result["error"])
        self.assertEqual(2, len(provider.prompts))
        self.assertLessEqual(len(provider.prompts[1]), config.max_prompt_chars)
        self.assertIn("candidate omitted to keep this correction bounded", provider.prompts[1])

    def test_r7_near_budget_initial_prompt_can_still_get_bounded_correction(self) -> None:
        config = X.ExtractionConfig(max_repair_attempts=1)
        ctx, request = self._near_budget_request(config)
        bad = valid_bundle(CHUNK_0, "刘表去世", time_original="建安十三年")
        good = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")
        provider = FakeProvider(
            [json.dumps(bad, ensure_ascii=False), json.dumps(good, ensure_ascii=False)]
        )

        result = X.extract_chunk(
            provider,
            request,
            chunk_text=CHUNK_0,
            context_input=ctx,
            section_label="全文",
            document=document(),
            schema=None,
            allowed_predicates=ALLOWED_PREDICATES,
            config=config,
        )

        self.assertTrue(result["accepted"], result["error"])
        self.assertEqual(2, len(provider.prompts))
        self.assertLessEqual(len(provider.prompts[1]), config.max_prompt_chars)
        self.assertIn("COMPACT CORRECTION RE-ASK", provider.prompts[1])
        self.assertIn("grounding:", provider.prompts[1])
        self.assertNotIn("PREVIOUS CANDIDATE", provider.prompts[1])


if __name__ == "__main__":
    unittest.main()
