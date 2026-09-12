"""Unit tests for the C2-R3-T14 third-round person-state gate.

Run::

    python3 -m unittest discover -s apps/chronicle/acceptance \
        -p 'test_third_round_gate.py' -v

These tests exercise the gate's pure decision/guard functions and the
deterministic fixture construction without Docker. The real-stack fixture run
is invoked separately by the acceptance command; this module proves the guard
rails fail closed and that the fixture provider emits candidates the owning
T01/reading/person-state and narrative validators accept.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for _path in (
    str(HERE),
    str(REPO / "apps" / "chronicle" / "persistence"),
    str(REPO / "apps" / "chronicle" / "worker"),
    str(REPO / "apps" / "chronicle" / "read_api"),
):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import chapter_contract  # noqa: E402
import chapter_extraction  # noqa: E402
import chapter_plan  # noqa: E402
import chapter_stage  # noqa: E402
import model_provider  # noqa: E402
import narrative_contract  # noqa: E402
import person_state_contract  # noqa: E402
import third_round_gate as G  # noqa: E402
from gate_runtime import GateError  # noqa: E402

CHAPTER_TEXT = """# 測試書

## 先主傳

劉備字玄德，涿郡涿縣人也。公孫瓚舉備為別部司馬。

## 周瑜傳

周瑜字公瑾，廬江舒人也。孫策與瑜為友。
"""


def _request(index: int = 0) -> dict:
    revision = "11111111-1111-7111-8111-111111111111"
    normalized = hashlib.sha256(CHAPTER_TEXT.encode("utf-8")).hexdigest()
    locator = {
        "revision_id": revision,
        "source_sha256": "a" * 64,
        "normalized_sha256": normalized,
    }
    limits = chapter_contract.ChapterLimits()
    plan = chapter_plan.plan_chapters(CHAPTER_TEXT, locator, "test.md", limits=limits)
    request = chapter_plan.build_chapter_request(plan, index, CHAPTER_TEXT, limits=limits)
    request["normalized_sha256"] = hashlib.sha256(
        request["normalized_text"].encode("utf-8")
    ).hexdigest()
    request["schema_versions"] = {"candidate": "0.3", "bundle": "0.1"}
    return request


def _narrative_context() -> dict:
    """A real-shaped synthesis context with one reviewed source state."""
    return {
        "catalog_sha": "c" * 64,
        "entities": {"ent_1": {"name": "周瑜", "kind": "person"}},
        "events": {"evt_1": {"name": "史料所述战事"}},
        "sources": [
            {
                "source_id": f"source_{index:03}",
                "publication_id": f"pub{index}",
                "document_id": "one-work",
                "source_sha": "a" * 64,
                "title": f"传{index}",
                "chapter_text": "瑜为偏将军，领南郡太守。",
                "translation": [{"text": "周瑜担任偏将军，兼任南郡太守。"}],
                "canonical_refs": {"entities": {"ent_1": "ent_1"}, "events": {"evt_1": "evt_1"}},
                "evidence": [
                    {
                        "id": f"e{index}",
                        "anchor_id": f"a{index}",
                        "quote": "瑜为偏将军，领南郡太守。",
                        "start": 0,
                        "end": 13,
                    }
                ],
                "reviewed_person_states": [
                    {
                        "person_id": "ent_1",
                        "person_name": "周瑜",
                        "dimension": "office",
                        "value": "偏将军",
                        "certainty": "clear",
                        "phase_ids": ["sph_001"],
                    }
                ],
            }
            for index in range(2)
        ],
    }


class FixtureCandidateTests(unittest.TestCase):
    def test_stack_env_to_provider_and_worker_accepts_person_state_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source_env = directory / "source.env"
            source_env.write_text("CHRONICLE_ADMIN_USER=admin\n", encoding="utf-8")
            env_path = G.write_stack_env(
                source_env, directory / "stack.env",
                endpoint="http://127.0.0.1:12345/v1/responses", web_port=8092,
            )
            model = chapter_stage.chapter_model_from_env(G.load_env_file(env_path))

        version = chapter_stage.candidate_version_for_model(model)
        _, requests = chapter_stage.plan_job_chapters(
            text=CHAPTER_TEXT,
            source_sha256=hashlib.sha256(CHAPTER_TEXT.encode("utf-8")).hexdigest(),
            binding={
                "revision_id": uuid.uuid5(uuid.NAMESPACE_URL, "c2r3-test"),
                "filename": "test.md",
            },
            limits=chapter_contract.ChapterLimits(), candidate_version=version,
        )
        bodies = []

        def fixture_response(req, timeout):
            body = json.loads(req.data.decode("utf-8"))
            bodies.append(body)
            response = mock.MagicMock()
            response.__enter__.return_value = response
            response.headers.get.return_value = None
            response.read.return_value = json.dumps(
                {"status": "completed", "output_text": G.chapter_candidate(body["input"])},
                ensure_ascii=False,
            ).encode("utf-8")
            return response

        with mock.patch.object(model_provider.request, "urlopen", side_effect=fixture_response):
            result = chapter_extraction.extract_chapter(requests[0], model)

        self.assertTrue(result["accepted"], result["error"])
        self.assertEqual("0.3", version)
        self.assertEqual("0.3", requests[0]["schema_versions"]["candidate"])
        self.assertEqual(1, len(bodies), "valid fixture must not need correction")
        body = bodies[0]
        self.assertNotIn("candidate_version", body, "version metadata is worker-local")
        schema = body["text"]["format"]["schema"]
        self.assertEqual("0.3", schema["properties"]["version"]["const"])
        Draft202012Validator(schema).validate(json.loads(G.chapter_candidate(body["input"])))
        self.assertEqual([], chapter_extraction.verify_history(result, request=requests[0]))

    def test_grounded_spec_and_person_state_candidate_validate(self):
        request = _request(0)
        spec = G.grounded_spec(request, "測試書")
        self.assertEqual(2, len(spec["entities"]))
        import fixture_model

        candidate = fixture_model.build_person_state_chapter_candidate(request, spec)
        self.assertEqual("0.3", candidate["version"])
        report = person_state_contract.validate_person_state_candidate(request, candidate)
        self.assertTrue(report)
        self.assertTrue(candidate["person_states"]["phases"])
        self.assertTrue(candidate["person_states"]["facts"])

    def test_chapter_candidate_round_trips_a_reconstructed_prompt(self):
        # The provider rebuilds the request from a production T05 prompt, so a
        # grounded candidate must survive the exact same path.
        request = _request(0)
        import fixture_model

        spec = G.grounded_spec(request, "測試書")
        candidate = fixture_model.build_person_state_chapter_candidate(request, spec)
        G.add_resolved_span(candidate, request)
        report = person_state_contract.validate_person_state_candidate(request, candidate)
        self.assertTrue(report)


class NarrativeDraftTests(unittest.TestCase):
    def test_fixture_drafts_pass_the_owning_contract(self):
        context = _narrative_context()
        facts, prose = G.narrative_drafts(context)
        G.add_reviewed_person_states(context, facts, prose)
        narrative_contract.validate_facts(facts, context)
        narrative_contract.validate_prose(prose, context, facts)
        self.assertTrue(any(item["dimension"] == "office" for item in facts["conclusions"]))

    def test_narrative_candidate_parses_a_real_prompt(self):
        context = _narrative_context()
        facts, _ = G.narrative_drafts(context)
        G.add_reviewed_person_states(context, facts, G.narrative_drafts(context)[1])
        prompt = (
            "instructions\nSTAGE=facts\nSCHEMA={}\nINPUT="
            + json.dumps(context, ensure_ascii=False)
        )
        payload = json.loads(G.narrative_candidate(prompt))
        self.assertIn("conclusions", payload)

    def test_narrative_context_rejects_a_prompt_without_input(self):
        with self.assertRaises(GateError):
            G._narrative_context("STAGE=facts\nno input here")


class GuardTests(unittest.TestCase):
    def test_no_direct_product_writes(self):
        result = G.check_no_direct_product_writes()
        self.assertFalse(result["direct_product_writes"])

    def test_source_state_inconsistencies_detects_409(self):
        probes = [
            {"status": 200, "unit_id": "ok"},
            {"status": 409, "unit_id": "bad", "error_code": "inconsistent"},
        ]
        self.assertEqual(
            [probe["unit_id"] for probe in G.source_state_inconsistencies(probes)],
            ["bad"],
        )
        self.assertEqual(G.source_state_inconsistencies([{"status": 200}]), [])

    def test_require_source_state_consistency_fails_closed(self):
        G.require_source_state_consistency([{"status": 200}, {"status": 404}])
        with self.assertRaises(GateError) as ctx:
            G.require_source_state_consistency(
                [{"status": 200}, {"status": 409, "unit_id": "bad"}]
            )
        self.assertIn("multi_chapter_source_state_consistency != PASS", str(ctx.exception))

    def test_fixture_env_refuses_fixture_packs(self):
        G.require_fixture_env({})
        for key in ("CHRONICLE_MODEL_FIXTURE_PACK", "CHRONICLE_CHAPTER_FIXTURE_PACK"):
            with self.assertRaises(GateError):
                G.require_fixture_env({key: "/tmp/pack.json"})

    def test_live_env_requires_both_models_and_no_credentials(self):
        base = {
            "CHRONICLE_POSTGRES_PASSWORD": "x",
            "CHRONICLE_ADMIN_USER": "admin",
            "CHRONICLE_ADMIN_PASSWORD": "y",
            "CHRONICLE_MODEL_ENDPOINT": "https://example.test/v1/responses",
            "CHRONICLE_EXTRACTION_MODEL": "e",
            "CHRONICLE_PRESENTATION_MODEL": "p",
            "CHRONICLE_CHAPTER_MODEL": "c",
            "CHRONICLE_NARRATIVE_MODEL": "n",
        }
        provider = G.require_live_env(dict(base))
        self.assertEqual("0.4", provider["candidate_version"])
        self.assertEqual("n", provider["narrative_model"])
        with self.assertRaises(GateError):
            G.require_live_env({**base, "CHRONICLE_NARRATIVE_MODEL": ""})
        with self.assertRaises(GateError):
            G.require_live_env(
                {**base, "CHRONICLE_MODEL_ENDPOINT": "https://u:p@example.test/v1"}
            )
        with self.assertRaises(GateError):
            G.require_live_env({**base, "CHRONICLE_CHAPTER_FIXTURE_PACK": "/tmp/x"})
        with self.assertRaisesRegex(GateError, "frozen fixture"):
            G.require_live_env({**base, "CHRONICLE_CHAPTER_MODEL": G.R3_CHAPTER_MODEL})


class BrowserManifestTests(unittest.TestCase):
    def _manifest(self) -> dict:
        return {
            "schema": G.BROWSER_MANIFEST_SCHEMA,
            "version": G.BROWSER_MANIFEST_VERSION,
            "history": {
                "version": "a" * 64,
                "catalog_sha": "b" * 64,
                "paragraph_id": "hp_" + "1" * 24,
                "phase_id": "ph_001",
                "entity_id": "entity_001",
                "state_id": "cf_001",
                "certainty": "clear",
                "paragraph_count": 3,
            },
            "source_person": {
                "stream_id": str(uuid.uuid4()),
                "catalog_sha": "c" * 64,
                "unit_id": "ru_" + "2" * 24,
                "person_id": "entity_001",
            },
            "review": {
                "review_scope": "all",
                "person_state_job_id": str(uuid.uuid4()),
            },
            "scale": {
                "stream_id": str(uuid.uuid4()),
                "catalog_sha": "d" * 64,
                "unit_count": 5000,
                "group_count": 1000,
                "first_unit_id": "ru_" + "3" * 24,
                "last_unit_id": "ru_" + "4" * 24,
            },
            "viewports": list(G.VIEWPORTS),
            "budgets": dict(G.PERF_BUDGETS),
        }

    def test_valid_manifest_passes(self):
        self.assertIsNotNone(G.validate_browser_manifest(self._manifest()))

    def test_missing_sections_fail_closed(self):
        for section in ("history", "source_person", "review", "scale"):
            manifest = self._manifest()
            manifest.pop(section)
            with self.assertRaises(GateError, msg=section):
                G.validate_browser_manifest(manifest)
        for field in (
            "version",
            "catalog_sha",
            "paragraph_id",
            "phase_id",
            "entity_id",
            "state_id",
        ):
            manifest = self._manifest()
            manifest["history"][field] = ""
            with self.assertRaises(GateError, msg=field):
                G.validate_browser_manifest(manifest)

    def test_short_scale_and_missing_budget_fail(self):
        manifest = self._manifest()
        manifest["scale"]["unit_count"] = 10
        with self.assertRaises(GateError):
            G.validate_browser_manifest(manifest)
        manifest = self._manifest()
        manifest["budgets"].pop("person_region_p95_ms")
        with self.assertRaises(GateError):
            G.validate_browser_manifest(manifest)


class CliTests(unittest.TestCase):
    def _run_gate(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(HERE / "third_round_gate.py"), *args],
            cwd=REPO,
            text=True,
            capture_output=True,
        )

    def test_missing_required_args_fail(self):
        result = self._run_gate("--mode", "fixture")
        self.assertNotEqual(0, result.returncode)

    def test_live_refuses_fixture_decisions(self):
        for flag in ("--auto-decide", "--non-interactive", "--execute"):
            result = self._run_gate(
                "--mode",
                "live",
                "--env-file",
                "/tmp/none.env",
                "--source-pack",
                str(REPO / "apps" / "chronicle" / "corpus" / "first-round" / "source-pack.json"),
                "--evidence-dir",
                "/tmp/chronicle-r3-live-unused",
                flag,
            )
            self.assertNotEqual(0, result.returncode, flag)
            self.assertIn("FAIL", result.stderr, flag)

    def test_live_requires_a_tty(self):
        result = self._run_gate(
            "--mode",
            "live",
            "--env-file",
            "/tmp/none.env",
            "--source-pack",
            str(REPO / "apps" / "chronicle" / "corpus" / "first-round" / "source-pack.json"),
            "--evidence-dir",
            "/tmp/chronicle-r3-live-unused",
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("interactive terminal", result.stderr)


if __name__ == "__main__":
    unittest.main()
