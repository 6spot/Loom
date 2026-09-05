#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("c1_t17_gate.py")
spec = importlib.util.spec_from_file_location("c1_t17_gate", MODULE_PATH)
assert spec and spec.loader
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)


class GateUnitTests(unittest.TestCase):
    def live(self) -> dict[str, str]:
        return {
            "CHRONICLE_POSTGRES_PASSWORD": "db-secret",
            "CHRONICLE_ADMIN_USER": "admin",
            "CHRONICLE_ADMIN_PASSWORD": "admin-secret",
            "CHRONICLE_MODEL_ENDPOINT": "https://provider.example/v1/responses?ignored=1",
            "CHRONICLE_MODEL_API_KEY": "provider-secret",
            "CHRONICLE_EXTRACTION_MODEL": "extract-model",
            "CHRONICLE_PRESENTATION_MODEL": "present-model",
        }

    def test_live_config_rejects_fixture(self) -> None:
        config = self.live()
        config["CHRONICLE_MODEL_FIXTURE_PACK"] = "/tmp/fixtures.json"
        with self.assertRaisesRegex(G.GateError, "refuses CHRONICLE_MODEL_FIXTURE_PACK"):
            G.require_live_config(config)

    def test_live_config_requires_models_and_endpoint(self) -> None:
        config = self.live()
        del config["CHRONICLE_EXTRACTION_MODEL"]
        with self.assertRaisesRegex(G.GateError, "CHRONICLE_EXTRACTION_MODEL"):
            G.require_live_config(config)

    def test_safe_provider_does_not_expose_secret_or_query(self) -> None:
        projected = G.safe_provider(self.live())
        self.assertEqual(projected["endpoint"], "https://provider.example/v1/responses")
        self.assertTrue(projected["api_key_present"])
        self.assertNotIn("provider-secret", repr(projected))
        self.assertFalse(projected["fixture_mode"])

    def test_env_parser_ignores_comments_and_blank_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("# note\nA=1\n\nB = two\n", encoding="utf-8")
            self.assertEqual(G.load_env_file(path), {"A": "1", "B": "two"})

    def test_sha256_is_stable(self) -> None:
        self.assertEqual(
            G.sha256_bytes(b"chronicle"),
            "43a52bc7d59d42b4020c698b3eff5e35c5f552b81d59eebde76594953a374bcb",
        )


if __name__ == "__main__":
    unittest.main()
