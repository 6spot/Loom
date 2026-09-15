"""Narrative model profiles are selectable without exposing transport secrets."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(HERE.parent / "worker") not in sys.path:
    sys.path.insert(0, str(HERE.parent / "worker"))

import narrative_model_settings
import narrative_models
from common import PersistenceConflict, PersistenceError, sha256_json


class NarrativeModelSettingsTests(unittest.TestCase):
    def env(self) -> dict[str, str]:
        return {
            "CHRONICLE_NARRATIVE_MODEL": "primary",
            "CHRONICLE_NARRATIVE_FACTS_MODELS": "facts-a,facts-b",
            "CHRONICLE_NARRATIVE_PROSE_MODELS": "prose-a",
            "CHRONICLE_NARRATIVE_COMPARE_MODELS": "reviewer",
            "CHRONICLE_MODEL_ENDPOINT": "https://provider.example/v1/responses",
            "CHRONICLE_MODEL_API_KEY": "secret-value",
        }

    def test_default_config_supports_independent_candidate_counts(self) -> None:
        config = narrative_model_settings.load_config(self.env())
        self.assertEqual(2, len(config["steps"]["facts_generate"]))
        self.assertEqual(1, len(config["steps"]["prose_generate"]))
        self.assertEqual(1, len(config["steps"]["facts_compare"]))
        self.assertEqual(config["steps"]["facts_compare"], config["steps"]["prose_compare"])

        models = narrative_models.from_env(self.env())
        self.assertEqual(("executor", "facts_generator"), models.steps["facts_generate"])
        self.assertEqual(("prose_generator",), models.steps["prose_generate"])
        self.assertEqual(600.0, models.timeout_seconds)
        self.assertNotIn("secret-value", json.dumps(models.public_config()))
        with self.assertRaisesRegex(PersistenceError, "durable step entry"):
            models.complete("old joint request")

    def test_json_config_and_global_timeout_are_frozen_per_job(self) -> None:
        config = {
            "version": "0.1",
            "models": {
                "facts_a": {"model": "facts-a"},
                "facts_b": {"model": "facts-b", "api_key_env": "FACTS_KEY"},
                "compare": {"model": "reviewer", "endpoint": "https://other.example/responses"},
            },
            "steps": {
                "facts_generate": ["facts_a", "facts_b"],
                "facts_compare/review": ["compare"],
                "prose_generate": ["facts_a"],
                "prose_compare": ["compare"],
            },
            "max_parallel": 1,
            "max_step_attempts": 2,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "narrative.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            env = {
                **self.env(),
                "CHRONICLE_NARRATIVE_MODEL": "",
                "CHRONICLE_NARRATIVE_PIPELINE_CONFIG": str(path),
                "FACTS_KEY": "another-secret",
                "CHRONICLE_MODEL_TIMEOUT_SECONDS": "45.5",
            }
            models = narrative_models.from_env(env)
            self.assertEqual(("facts_a", "facts_b"), models.steps["facts_generate"])
            self.assertEqual(45.5, models.model_for("facts_generate", "facts_a").timeout_seconds)
            self.assertEqual(1, models.max_parallel)
            self.assertEqual(2, models.max_step_attempts)
            self.assertNotIn("another-secret", json.dumps(models.public_config()))

    def test_catalog_is_credential_free_and_selection_rejects_drift(self) -> None:
        choices = narrative_model_settings.catalog(self.env())
        self.assertTrue(choices["available"])
        self.assertNotIn("provider.example", json.dumps(choices))
        self.assertNotIn("secret-value", json.dumps(choices))
        selection = {"config_sha256": choices["config_sha256"], "steps": choices["steps"]}
        self.assertEqual(selection, narrative_model_settings.validate_selection(selection, choices))
        with self.assertRaises(PersistenceConflict):
            narrative_model_settings.validate_selection(
                {**selection, "config_sha256": "0" * 64}, choices
            )
        with self.assertRaises(PersistenceError):
            narrative_model_settings.validate_selection(
                {**selection, "steps": {**selection["steps"], "facts_generate": ["missing"]}},
                choices,
            )

        models = narrative_models.from_env(self.env())
        selected = models.for_selection(selection)
        self.assertEqual(models.steps, selected.steps)
        self.assertEqual(sha256_json(models.public_config()), sha256_json(selected.public_config()))

    def test_fixture_and_profile_timeout_configuration_fail_closed(self) -> None:
        with self.assertRaisesRegex(PersistenceError, "fixture"):
            narrative_models.from_env({
                "CHRONICLE_NARRATIVE_MODEL": "fixture:narrative",
                "CHRONICLE_MODEL_ENDPOINT": "https://provider.example/responses",
            })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "narrative.json"
            config = narrative_model_settings.load_config(self.env())
            config["models"][next(iter(config["models"]))]["timeout_seconds"] = 30
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(PersistenceError, "CHRONICLE_MODEL_TIMEOUT_SECONDS"):
                narrative_models.from_env({**self.env(), "CHRONICLE_NARRATIVE_PIPELINE_CONFIG": str(path)})


if __name__ == "__main__":
    unittest.main()
