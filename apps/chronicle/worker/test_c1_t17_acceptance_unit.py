#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ACCEPTANCE_DIR = Path(__file__).resolve().parents[1] / "acceptance"
if str(ACCEPTANCE_DIR) not in sys.path:
    sys.path.insert(0, str(ACCEPTANCE_DIR))

MODULE_PATH = ACCEPTANCE_DIR / "c1_t17_gate.py"
WORLD_BROWSER_PATH = ACCEPTANCE_DIR / "world_browser_smoke.py"
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
        with self.assertRaisesRegex(G.S.GateError, "refuses CHRONICLE_MODEL_FIXTURE_PACK"):
            G.require_strict_live_config(config)

    def test_strict_config_rejects_endpoint_credentials(self) -> None:
        config = self.live()
        config["CHRONICLE_MODEL_ENDPOINT"] = "https://user:secret@provider.example/v1/responses"
        with self.assertRaisesRegex(G.S.GateError, "must not embed credentials"):
            G.require_strict_live_config(config)

    def test_safe_provider_does_not_expose_secret_or_query(self) -> None:
        projected = G.S.safe_provider(self.live())
        self.assertEqual(projected["endpoint"], "https://provider.example/v1/responses")
        self.assertTrue(projected["api_key_present"])
        self.assertNotIn("provider-secret", repr(projected))
        self.assertFalse(projected["fixture_mode"])

    def test_env_parser_ignores_comments_and_blank_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("# note\nA=1\n\nB = two\n", encoding="utf-8")
            self.assertEqual(G.S.load_env_file(path), {"A": "1", "B": "two"})

    def test_compose_env_forces_gate_lease_and_worker(self) -> None:
        env = G.compose_env(G.WORKER_B)
        self.assertEqual(
            env["CHRONICLE_WORKER_LEASE_SECONDS"], str(G.GATE_LEASE_SECONDS)
        )
        self.assertEqual(env["CHRONICLE_WORKER_ID"], G.WORKER_B)

    def test_moment_summary_is_deterministic(self) -> None:
        payload = {
            "catalog": {"artifact_sha256": "a" * 64},
            "events": [
                {"canonical_event_id": "b"},
                {"canonical_event_id": "a"},
            ],
            "entities": [{}, {}],
            "places": [{}],
            "polities": [],
            "coverage": {"represented": True},
        }
        summary = G.moment_summary(payload)
        self.assertEqual(summary["event_ids"], ["a", "b"])
        self.assertEqual(summary["entity_count"], 2)
        self.assertEqual(summary["place_count"], 1)

    def test_long_lived_worker_is_stopped_before_job_queue(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        stop_marker = 'evidence_dir / "worker-stop-before-queue.txt"'
        queue_marker = "job = S.queue_job("
        self.assertIn(stop_marker, source)
        self.assertIn(queue_marker, source)
        self.assertLess(source.index(stop_marker), source.index(queue_marker))

    def test_world_browser_contract_matches_gate_invocation(self) -> None:
        gate_source = MODULE_PATH.read_text(encoding="utf-8")
        browser_source = WORLD_BROWSER_PATH.read_text(encoding="utf-8")
        compile(browser_source, str(WORLD_BROWSER_PATH), "exec")
        self.assertIn('parser.add_argument("--event-id", required=True)', browser_source)
        self.assertNotIn('parser.add_argument("--evidence-sha256"', browser_source)
        self.assertIn('data-view="world"', browser_source)
        self.assertIn("support_evidence", browser_source)
        self.assertIn('"--event-id", public_sample["event_id"]', gate_source)


if __name__ == "__main__":
    unittest.main()
