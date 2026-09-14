"""Focused tests for the single staged 0.4 acceptance entry."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for path in (
    HERE,
    REPO / "apps" / "chronicle" / "persistence",
    REPO / "apps" / "chronicle" / "worker",
    REPO / "apps" / "chronicle" / "read_api",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import chapter_contract  # noqa: E402
import chapter_plan  # noqa: E402
import chapter_production  # noqa: E402
import chapter_stage  # noqa: E402
import staged_chapter_contract  # noqa: E402
import staged_pipeline_fixture as fixture  # noqa: E402
import staged_gate as gate  # noqa: E402
from gate_runtime import GateError, load_env_file  # noqa: E402


CHAPTER_TEXT = (
    "# 测试书\n\n"
    "## 第一章\n\n"
    "刘备字玄德，涿郡涿县人也。公孙瓒举备为别部司马。\n\n"
    "〈裴松之注：另說不確，仍存。〉\n\n"
    "## 第二章\n\n"
    "周瑜字公瑾，庐江舒人也。孙策与瑜为友。"
)


def _request(text: str = CHAPTER_TEXT) -> dict:
    source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    _plan, requests = chapter_stage.plan_job_chapters(
        text=text,
        source_sha256=source_sha,
        binding={
            "revision_id": "11111111-1111-7111-8111-111111111111",
            "filename": "test.md",
        },
        limits=chapter_contract.ChapterLimits(),
        candidate_version="0.4",
    )
    return requests[0]


def _source_view(request: dict) -> dict:
    source = copy.deepcopy({
        key: request[key]
        for key in (
            "chapter_id",
            "title",
            "source_sha256",
            "normalized_sha256",
            "normalized_text",
            "blocks",
            "required_block_ids",
            "source_scope",
        )
    })
    for block in source["blocks"]:
        block["text"] = source["normalized_text"][block["start"] : block["end"]]
    for fragment in source["source_scope"]["fragments"]:
        fragment["text"] = source["normalized_text"][fragment["start"] : fragment["end"]]
    return source


class StagedFixtureTests(unittest.TestCase):
    def test_arbitrary_source_produces_a_current_candidate(self):
        request = _request()
        candidate = fixture.candidate_for_source(_source_view(request))
        report = staged_chapter_contract.validate_staged_candidate(request, candidate)
        self.assertTrue(report["passed"], report)
        self.assertEqual("0.4", candidate["version"])
        self.assertEqual(request["source_scope"], candidate["source_scope"])
        self.assertEqual(
            request["required_block_ids"],
            candidate["translation"]["blocks"][0]["source_block_ids"],
        )
        self.assertTrue(candidate["reading"]["units"])
        self.assertTrue(candidate["person_states"]["phases"])

    def test_translation_spans_use_normalized_translation_coordinates(self):
        request = _request(
            "# 三國志\n\n## 第一章\n\n"
            "劉備字玄德，涿郡涿縣人也。周瑜字公瑾，廬江舒人也。"
        )
        candidate = fixture.candidate_for_source(_source_view(request))
        normalized = chapter_production.translation_document(
            candidate["translation"]["blocks"][0]["text"]
        )
        candidate["translation"]["blocks"][0]["text"] = normalized["blocks"][0]["text"]
        report = staged_chapter_contract.validate_staged_candidate(request, candidate)
        self.assertTrue(report["passed"], report)
        span = candidate["reading"]["units"][0]["event_spans"][0]
        self.assertIn(
            span["selection"]["quote"],
            candidate["translation"]["blocks"][0]["text"],
        )
        self.assertNotEqual(span["selection"]["quote"], candidate["mentions"][0]["surface"])

    def test_prompt_fixture_runs_the_same_six_step_contract(self):
        request = _request()
        source = _source_view(request)
        script = fixture.ScriptedModels()
        self.assertEqual("0.4", script.models.candidate_version)
        self.assertEqual(
            set(chapter_production.STEPS), set(script.models.steps)
        )
        translation = script.complete(
            "translation",
            "executor",
            "CHRONICLE_STEP=translation\nSOURCE="
            + json.dumps(source, ensure_ascii=False)
            + "\nDATA={}",
        )
        self.assertIn("fixture", translation)
        extraction = script.complete(
            "extraction",
            "executor",
            "CHRONICLE_STEP=extraction\nSOURCE="
            + json.dumps(source, ensure_ascii=False)
            + "\nDATA={}",
        )
        Draft202012Validator(
            chapter_production.step_schema("extraction")
        ).validate(json.loads(extraction))

    def test_http_fixture_is_the_current_provider_boundary(self):
        provider = fixture.StagedFixtureProvider(gate.free_port())
        provider.start()
        try:
            request = _request()
            prompt = chapter_production.build_prompt(
                "translation", request, {}, max_chars=chapter_contract.ChapterLimits().max_prompt_chars
            )
            from urllib.request import Request, urlopen

            body = json.dumps({"model": gate.STAGED_CHAPTER_MODEL, "input": prompt}).encode()
            with urlopen(
                Request(
                    f"http://127.0.0.1:{provider.port}/v1/responses",
                    data=body,
                    headers={"Content-Type": "application/json"},
                ),
                timeout=5,
            ) as response:
                payload = json.loads(response.read())
            self.assertEqual("completed", payload["status"])
            self.assertIn("fixture", payload["output"][0]["content"][0]["text"])
            self.assertEqual(["chapter:translation"], provider.calls)
        finally:
            provider.stop()

    def test_stack_env_selects_production_0_4_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.env"
            source.write_text(
                "CHRONICLE_ADMIN_USER=admin\n"
                "CHRONICLE_ADMIN_PASSWORD=test\n"
                "CHRONICLE_MODEL_API_KEY=must-not-be-copied\n"
                "CHRONICLE_MODEL_FIXTURE_PACK=/old/pack.json\n",
                encoding="utf-8",
            )
            output = gate.write_stack_env(
                source,
                root / "stack.env",
                endpoint="http://host.docker.internal:12345/v1/responses",
                web_port=18080,
            )
            config = load_env_file(output)
            self.assertEqual(gate.STAGED_CHAPTER_MODEL, config["CHRONICLE_CHAPTER_MODEL"])
            self.assertNotIn("CHRONICLE_MODEL_API_KEY", config)
            self.assertNotIn("CHRONICLE_MODEL_FIXTURE_PACK", config)
            models = chapter_stage.chapter_model_from_env(config)
            self.assertEqual("0.4", models.candidate_version)
            self.assertTrue(models.model_for("translation", "executor"))


class GuardTests(unittest.TestCase):
    def test_no_direct_product_writes(self):
        self.assertFalse(gate.check_no_direct_product_writes()["direct_product_writes"])

    def test_fixture_mode_rejects_external_fixture_packs(self):
        for key in ("CHRONICLE_MODEL_FIXTURE_PACK", "CHRONICLE_CHAPTER_FIXTURE_PACK"):
            with self.assertRaises(GateError):
                gate.require_fixture_env({key: "/tmp/fixture.json"})

    def test_live_mode_requires_current_models_and_never_fixture_falls_back(self):
        base = {
            "CHRONICLE_POSTGRES_PASSWORD": "test",
            "CHRONICLE_ADMIN_USER": "admin",
            "CHRONICLE_ADMIN_PASSWORD": "test",
            "CHRONICLE_MODEL_ENDPOINT": "https://provider.example/v1/responses",
            "CHRONICLE_CHAPTER_MODEL": "chapter-live",
            "CHRONICLE_CHAPTER_REVIEW_MODELS": "review-live",
            "CHRONICLE_NARRATIVE_MODEL": "narrative-live",
        }
        result = gate.require_live_env(dict(base))
        self.assertEqual("0.4", result["candidate_version"])
        self.assertEqual("chapter-live", result["chapter_model"])
        for patch in (
            {"CHRONICLE_CHAPTER_FIXTURE_PACK": "/tmp/x"},
            {"CHRONICLE_CHAPTER_MODEL": gate.STAGED_CHAPTER_MODEL},
            {"CHRONICLE_NARRATIVE_MODEL": "fixture:narrative"},
            {"CHRONICLE_CHAPTER_REVIEW_MODELS": "review-live,fixture:review"},
            {"CHRONICLE_MODEL_ENDPOINT": "https://u:p@provider.example/v1"},
        ):
            with self.subTest(patch=patch), self.assertRaises(GateError):
                gate.require_live_env({**base, **patch})

    def test_live_mode_reports_missing_credentials_without_fallback(self):
        with self.assertRaisesRegex(GateError, "missing required live-gate configuration"):
            gate.require_live_env({})

    def test_source_state_consistency_fails_closed(self):
        gate.require_source_state_consistency([{"status": 200}])
        with self.assertRaisesRegex(GateError, "multi_chapter_source_state_consistency"):
            gate.require_source_state_consistency([{"status": 409, "unit_id": "bad"}])


class BrowserManifestTests(unittest.TestCase):
    def _manifest(self):
        return {
            "schema": gate.BROWSER_MANIFEST_SCHEMA,
            "version": gate.BROWSER_MANIFEST_VERSION,
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
                "stream_id": "stream",
                "catalog_sha": "c" * 64,
                "unit_id": "unit",
                "person_id": "entity_001",
            },
            "review": {"review_scope": "all", "person_state_job_id": "job"},
            "scale": {
                "stream_id": "scale",
                "catalog_sha": "d" * 64,
                "unit_count": 5000,
                "group_count": 1000,
            },
            "viewports": list(gate.VIEWPORTS),
            "budgets": dict(gate.PERF_BUDGETS),
        }

    def test_valid_manifest(self):
        manifest = self._manifest()
        self.assertIs(gate.validate_browser_manifest(manifest), manifest)

    def test_incomplete_manifest_fails_closed(self):
        manifest = self._manifest()
        manifest.pop("history")
        with self.assertRaises(GateError):
            gate.validate_browser_manifest(manifest)
        manifest = self._manifest()
        manifest["scale"]["unit_count"] = 10
        with self.assertRaises(GateError):
            gate.validate_browser_manifest(manifest)


class CliTests(unittest.TestCase):
    def _run_gate(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(HERE / "staged_gate.py"), *args],
            cwd=REPO,
            text=True,
            capture_output=True,
        )

    def test_missing_required_args_fail(self):
        result = self._run_gate("--mode", "fixture")
        self.assertNotEqual(0, result.returncode)

    def test_live_never_accepts_automatic_decisions(self):
        for flag in ("--auto-decide", "--non-interactive", "--execute"):
            result = self._run_gate(
                "--mode", "live",
                "--env-file", "/tmp/none.env",
                "--source-pack", "apps/chronicle/corpus/first-round/source-pack.json",
                "--evidence-dir", "/tmp/chronicle-staged-live-unused",
                flag,
            )
            self.assertNotEqual(0, result.returncode, flag)
            self.assertIn("FAIL", result.stderr, flag)

    def test_live_requires_a_tty(self):
        result = self._run_gate(
            "--mode", "live",
            "--env-file", "/tmp/none.env",
            "--source-pack", "apps/chronicle/corpus/first-round/source-pack.json",
            "--evidence-dir", "/tmp/chronicle-staged-live-unused",
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("interactive terminal", result.stderr)


if __name__ == "__main__":
    unittest.main()
