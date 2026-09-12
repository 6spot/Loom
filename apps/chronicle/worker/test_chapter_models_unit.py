"""Production profile validation and per-step transport selection."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
for path in (HERE, HERE.parent / "persistence"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import chapter_models
import chapter_production
import chapter_stage
from chapter_contract import ChapterLimits
from common import PersistenceError, sha256_json


class ChapterModelsTests(unittest.TestCase):
    def env(self):
        return {"CHRONICLE_CHAPTER_MODEL": "luna", "CHRONICLE_MODEL_ENDPOINT": "https://gateway.example/v1/responses",
                "CHRONICLE_MODEL_API_KEY": "test-secret"}

    def configured(self, config, env=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "models.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            return chapter_models.from_env({**(env or self.env()), "CHRONICLE_CHAPTER_PIPELINE_CONFIG": str(path)}, limits=ChapterLimits())

    def config(self):
        return {"version": "0.1", "models": {"a": {"model": "luna"}, "b": {"model": "reviewer", "api_key_env": "REVIEW_KEY"}},
                "steps": {step: ["a"] for step in chapter_production.STEPS}}

    def test_default_is_staged_pure_translation_and_separate_review(self):
        model = chapter_models.from_env(self.env(), limits=ChapterLimits())
        self.assertEqual(model.candidate_version, "0.4")
        self.assertIsNone(model.model_for("translation", "executor").text_format)
        self.assertEqual(model.model_for("extraction", "executor").text_format, {"type": "json_object"})
        self.assertEqual(model.config_for("translation", "executor")["response_format"], "text")
        self.assertEqual(model.max_parallel, 2)
        self.assertEqual(model.max_step_attempts, 2)
        self.assertEqual(model.max_repair_rounds, 1)
        self.assertEqual(model.config_for("review", "reviewer_1")["total_timeout_seconds"], 360)
        with self.assertRaisesRegex(PersistenceError, "durable chapter entry"):
            model.complete("cannot call old joint entry")

    def test_each_step_supports_multiple_independent_profiles(self):
        config = self.config()
        config["steps"] = {step: ["a", "b"] for step in chapter_production.STEPS}
        config["models"]["b"].update({"endpoint": "https://other.example/responses", "max_output_tokens": 4096,
                                         "total_timeout_seconds": 60, "response_format": "text"})
        model = self.configured(config, {**self.env(), "REVIEW_KEY": "second-secret"})
        for step in chapter_production.STEPS:
            self.assertEqual(model.steps[step], ("a", "b"))
            self.assertEqual(model.model_for(step, "b").max_output_tokens, 4096)
            self.assertIsNone(model.model_for(step, "b").text_format)
            self.assertEqual(model.config_for(step, "b")["total_timeout_seconds"], 60)
        public = json.dumps(model.public_config())
        self.assertNotIn("second-secret", public)
        self.assertNotIn("test-secret", public)
        self.assertIn("REVIEW_KEY", public)

    def test_credentials_rotate_without_changing_frozen_config(self):
        first = chapter_models.from_env(self.env(), limits=ChapterLimits())
        second = chapter_models.from_env({**self.env(), "CHRONICLE_MODEL_API_KEY": "rotated"}, limits=ChapterLimits())
        self.assertEqual(sha256_json(first.public_config()), sha256_json(second.public_config()))

    def test_model_or_policy_changes_change_config_fingerprint(self):
        baseline = self.configured(self.config()).public_config()
        for key, value in (("max_parallel", 1), ("max_step_attempts", 3), ("max_repair_rounds", 0)):
            config = self.config()
            config[key] = value
            self.assertNotEqual(sha256_json(baseline), sha256_json(self.configured(config).public_config()))
        config = self.config()
        config["models"]["a"]["model"] = "another-model"
        self.assertNotEqual(sha256_json(baseline), sha256_json(self.configured(config).public_config()))

    def test_invalid_profile_configuration_is_rejected_at_startup(self):
        cases = []
        for key, value in (("api_key", "secret"), ("endpoint", 17), ("endpoint", "https://gateway.example?api_key=secret"),
                           ("total_timeout_seconds", 0), ("total_timeout_seconds", float("inf")),
                           ("max_output_tokens", True), ("response_format", "unsupported")):
            config = self.config()
            config["models"]["a"][key] = value
            cases.append(config)
        for slots in ([], ["missing"], ["a", "a"], [{}]):
            config = self.config()
            config["steps"]["translation"] = slots
            cases.append(config)
        for key, value in (("max_parallel", 5), ("max_repair_rounds", 2), ("max_step_attempts", 0)):
            config = self.config()
            config[key] = value
            cases.append(config)
        for config in cases:
            with self.subTest(config=config), self.assertRaises(PersistenceError):
                self.configured(config)

    def test_fixture_pack_cannot_hide_live_pipeline_config(self):
        with self.assertRaisesRegex(PersistenceError, "cannot be combined"):
            chapter_stage.chapter_model_from_env({"CHRONICLE_CHAPTER_FIXTURE_PACK": "unused.json",
                                                 "CHRONICLE_CHAPTER_PIPELINE_CONFIG": "live.json"})


if __name__ == "__main__":
    unittest.main()
