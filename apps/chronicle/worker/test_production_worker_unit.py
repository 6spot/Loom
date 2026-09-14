"""Production selects staged chapters and refuses incomplete configuration."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
for path in (HERE, PERSISTENCE):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

import production_worker as P  # noqa: E402


class ChapterEntryTests(unittest.TestCase):
    def test_chapter_defaults_match_chapter_production_section3(self) -> None:
        limits, model = P.chapter_configs({})

        self.assertIsNone(model)
        self.assertEqual(32768, limits.max_source_chars)
        self.assertEqual(262144, limits.max_prompt_chars)
        self.assertEqual(524288, limits.max_response_chars)
        self.assertEqual(4 * 1024 * 1024, limits.max_response_bytes)
        self.assertEqual(65536, limits.max_output_tokens)
        self.assertEqual(1, limits.max_correction_rounds)

    def test_chapter_env_overrides_are_honored(self) -> None:
        limits, _ = P.chapter_configs(
            {
                "CHRONICLE_CHAPTER_MAX_SOURCE_CHARS": "4096",
                "CHRONICLE_CHAPTER_MAX_OUTPUT_TOKENS": "1024",
            }
        )

        self.assertEqual(4096, limits.max_source_chars)
        self.assertEqual(1024, limits.max_output_tokens)
        self.assertEqual(262144, limits.max_prompt_chars)

    def test_chapter_invalid_env_is_rejected(self) -> None:
        with self.assertRaises(P.PersistenceError):
            P.chapter_configs({"CHRONICLE_CHAPTER_MAX_SOURCE_CHARS": "0"})
        with self.assertRaises(P.PersistenceError):
            P.chapter_configs({"CHRONICLE_CHAPTER_MAX_PROMPT_CHARS": "not-an-int"})

    def test_chapter_model_without_endpoint_fails_closed(self) -> None:
        with self.assertRaisesRegex(P.PersistenceError, "CHRONICLE_MODEL_ENDPOINT"):
            P.chapter_configs({"CHRONICLE_CHAPTER_MODEL": "loom-chapter"})

    def test_chapter_fixture_pack_missing_file_fails_closed(self) -> None:
        with self.assertRaises(P.PersistenceError):
            P.chapter_configs(
                {"CHRONICLE_CHAPTER_FIXTURE_PACK": "/nonexistent/pack.json"}
            )

    def test_chapter_fixture_pack_conflicts_with_live_model(self) -> None:
        with self.assertRaises(P.PersistenceError):
            P.chapter_configs(
                {
                    "CHRONICLE_CHAPTER_FIXTURE_PACK": "/tmp/pack.json",
                    "CHRONICLE_CHAPTER_MODEL": "loom-chapter",
                }
            )


class ProductionEntryTests(unittest.TestCase):
    def test_missing_source_or_model_is_rejected(self) -> None:
        for source, model, message in (
            (None, None, "CHRONICLE_SOURCE_DIR"),
            (None, SimpleNamespace(candidate_version="0.4"), "CHRONICLE_SOURCE_DIR"),
            ("/data/sources", None, "CHRONICLE_CHAPTER_MODEL"),
        ):
            with self.subTest(source=source, model=model):
                with self.assertRaisesRegex(P.PersistenceError, message):
                    P.chapter_stage.require_production_entry(
                        source_dir=source, chapter_model=model,
                    )

    def test_old_and_undeclared_provider_contracts_are_rejected(self) -> None:
        for version in (None, "0.1", "0.2", "0.3"):
            with self.subTest(version=version):
                with self.assertRaisesRegex(P.PersistenceError, "staged chapter 0.4"):
                    P.chapter_stage.require_production_entry(
                        source_dir="/data/sources",
                        chapter_model=SimpleNamespace(candidate_version=version),
                    )

    def test_staged_provider_is_accepted(self) -> None:
        P.chapter_stage.require_production_entry(
            source_dir="/data/sources",
            chapter_model=SimpleNamespace(candidate_version="0.4"),
        )

    def test_production_wires_staged_limits_source_and_narrative_once(self) -> None:
        chapter = SimpleNamespace(candidate_version="0.4", name="staged")
        narrative = object()
        revision_source = mock.Mock()
        limits = P.chapter_stage.chapter_contract.ChapterLimits(max_source_chars=4096)
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            P, "chapter_configs", return_value=(limits, chapter)
        ), mock.patch.object(
            P.worker, "build_revision_source", return_value=revision_source
        ) as build_source, mock.patch.object(
            P.worker.narrative_stage, "model_from_env", return_value=narrative
        ), mock.patch.object(
            P.worker.model_provider, "models_from_env",
            side_effect=AssertionError("production must not construct C1 providers"),
        ), mock.patch.object(
            P.worker, "install_shutdown_handlers"
        ), mock.patch.object(P.worker, "run_forever", return_value={}) as run:
            result = P.main([
                "--database-url", "postgresql://localhost/chronicle",
                "--worker-id", "entry-test", "--source-dir", "/data/sources",
                "--max-jobs", "0",
            ])
        self.assertEqual(result, 0)
        build_source.assert_called_once_with(
            "postgresql://localhost/chronicle", Path("/data/sources")
        )
        run.assert_called_once()
        kwargs = run.call_args.kwargs
        self.assertIs(kwargs["chapter_model"], chapter)
        self.assertIs(kwargs["chapter_limits"], limits)
        self.assertIs(kwargs["revision_source"], revision_source)
        self.assertIs(kwargs["narrative_model"], narrative)
        for retired in ("chunk_model", "presentation_model", "segmentation_config",
                        "extraction_config", "executor_factory"):
            self.assertNotIn(retired, kwargs)

    def test_incomplete_config_and_old_model_knobs_cannot_claim_jobs(self) -> None:
        for overrides in (
            {},
            {"CHRONICLE_SOURCE_DIR": "/data/sources"},
            {"CHRONICLE_SOURCE_DIR": "/data/sources",
             "CHRONICLE_EXTRACTION_MODEL": "old-extraction",
             "CHRONICLE_PRESENTATION_MODEL": "old-presentation"},
        ):
            with self.subTest(overrides=overrides), mock.patch.dict(
                os.environ, overrides, clear=True
            ), mock.patch.object(P.worker, "run_forever") as run:
                with self.assertRaises(P.PersistenceError):
                    P.main(["--database-url", "postgresql://localhost/chronicle"])
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
