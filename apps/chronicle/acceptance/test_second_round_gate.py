#!/usr/bin/env python3
"""Scoped offline tests for the C2-R2-T16 second-round reading gate.

Covers the gate decision/boundary logic owned by this task, without a live
stack:

- the fixture pack is deterministic, grounded verbatim in the planned chapter
  text, and bound to the product revision identity;
- the fixture/live provider guards fail closed (live model in fixture mode,
  fixture material/credentials in live mode, missing joint chapter model);
- the browser fixture manifest is required and must be complete, so a missing
  fixture/scene/manifest fails the harness instead of silently passing;
- the orchestrator carries no direct product-table writes;
- the live entry refuses automatic decisions, non-interactive review and
  execution;
- the isolated Compose project name is prefixed so a gate never touches an
  operator deployment.

The real PG18 reading chain is exercised by the gate itself (fixture mode)
and by the product PostgreSQL suites; it is not faked here.

Run::

    python3 -m unittest discover -s apps/chronicle/acceptance \
        -p 'test_second_round_gate.py' -v
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

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for path in (
    str(HERE),
    str(REPO / "apps/chronicle/persistence"),
    str(REPO / "apps/chronicle/worker"),
    str(REPO / "apps/chronicle/read_api"),
):
    if path not in sys.path:
        sys.path.insert(0, path)

import second_round_gate as G  # noqa: E402
from gate_runtime import Evidence, GateError, default_gate_project  # noqa: E402

GATE = HERE / "second_round_gate.py"
SOURCE_PACK = REPO / "apps/chronicle/corpus/first-round/source-pack.json"

TINY_TEXT = (
    "# Fixture書\n\n## 上章\n\n甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥。\n\n"
    "## 下章\n\n天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往秋收冬藏。\n"
)


def write_env(directory: Path, extra: str = "") -> Path:
    path = directory / "second-round-test.env"
    path.write_text(
        "CHRONICLE_POSTGRES_PASSWORD=test-only\n"
        "CHRONICLE_ADMIN_USER=admin\n"
        "CHRONICLE_ADMIN_PASSWORD=test-only\n" + extra,
        encoding="utf-8",
    )
    return path


def live_env(directory: Path, extra: str = "") -> Path:
    return write_env(
        directory,
        "CHRONICLE_MODEL_ENDPOINT=https://example.test/v1/responses\n"
        "CHRONICLE_EXTRACTION_MODEL=fixture-extract\n"
        "CHRONICLE_PRESENTATION_MODEL=fixture-present\n"
        "CHRONICLE_CHAPTER_MODEL=fixture-chapter\n" + extra,
    )


def tiny_upload() -> dict:
    raw = TINY_TEXT.encode("utf-8")
    return {
        "work": "Fixture書",
        "upload": "tiny.md",
        "path": "/nonexistent/tiny.md",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "chars": len(TINY_TEXT),
        "text": TINY_TEXT,
    }


def tiny_planned() -> dict:
    revision_id = uuid.uuid5(uuid.NAMESPACE_URL, "c2r2-test")
    return G.plan_upload(tiny_upload(), revision_id)


def run_gate(*args: str, stdin_data: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE), *args],
        cwd=REPO,
        text=True,
        capture_output=True,
        input=stdin_data,
    )


class FixtureConstructionTests(unittest.TestCase):
    def test_pack_is_deterministic_and_bound_to_revision(self) -> None:
        planned = tiny_planned()
        first = G.reading_fixture_pack(planned, "Fixture書")
        second = G.reading_fixture_pack(planned, "Fixture書")
        self.assertEqual(first, second)
        self.assertEqual(first["schema"], "chronicle.chapter-fixture-pack")
        self.assertEqual(first["version"], "0.1")
        self.assertEqual(len(first["chapters"]), len(planned["plan"]["chapters"]))
        for chapter in first["chapters"]:
            self.assertEqual(chapter["revision_id"], planned["plan"]["revision_id"])

    def test_pack_mentions_are_grounded_in_chapter_text(self) -> None:
        from chapter_contract import ChapterLimits
        import chapter_plan

        planned = tiny_planned()
        plan, text = planned["plan"], planned["text"]
        pack = G.reading_fixture_pack(planned, "Fixture書")
        self.assertEqual(len(pack["chapters"]), len(plan["chapters"]))
        for index, chapter in enumerate(pack["chapters"]):
            request = chapter_plan.build_chapter_request(
                plan, index, text, limits=ChapterLimits()
            )
            for entity in chapter["entities"]:
                self.assertIn(entity["mention"], request["normalized_text"])

    def test_fixture_mode_refuses_live_model(self) -> None:
        with self.assertRaises(GateError) as ctx:
            G.require_fixture_env({"CHRONICLE_CHAPTER_MODEL": "live"})
        self.assertIn("CHRONICLE_CHAPTER_MODEL", str(ctx.exception))
        G.require_fixture_env({})


class LiveProviderGuardTests(unittest.TestCase):
    def test_live_refuses_fixture_pack(self) -> None:
        config = {
            "CHRONICLE_POSTGRES_PASSWORD": "x",
            "CHRONICLE_ADMIN_USER": "admin",
            "CHRONICLE_ADMIN_PASSWORD": "x",
            "CHRONICLE_MODEL_ENDPOINT": "https://example.test/v1",
            "CHRONICLE_EXTRACTION_MODEL": "m1",
            "CHRONICLE_PRESENTATION_MODEL": "m2",
            "CHRONICLE_CHAPTER_MODEL": "m3",
            "CHRONICLE_CHAPTER_FIXTURE_PACK": "/tmp/pack.json",
        }
        with self.assertRaises(GateError) as ctx:
            G.require_live_env(config)
        self.assertIn("FIXTURE_PACK", str(ctx.exception))

    def test_live_requires_joint_chapter_model(self) -> None:
        config = {
            "CHRONICLE_POSTGRES_PASSWORD": "x",
            "CHRONICLE_ADMIN_USER": "admin",
            "CHRONICLE_ADMIN_PASSWORD": "x",
            "CHRONICLE_MODEL_ENDPOINT": "https://example.test/v1",
            "CHRONICLE_EXTRACTION_MODEL": "m1",
            "CHRONICLE_PRESENTATION_MODEL": "m2",
        }
        with self.assertRaises(GateError) as ctx:
            G.require_live_env(config)
        self.assertIn("CHRONICLE_CHAPTER_MODEL", str(ctx.exception))

    def test_live_refuses_endpoint_credentials(self) -> None:
        config = {
            "CHRONICLE_POSTGRES_PASSWORD": "x",
            "CHRONICLE_ADMIN_USER": "admin",
            "CHRONICLE_ADMIN_PASSWORD": "x",
            "CHRONICLE_MODEL_ENDPOINT": "https://user:pass@example.test/v1",
            "CHRONICLE_EXTRACTION_MODEL": "m1",
            "CHRONICLE_PRESENTATION_MODEL": "m2",
            "CHRONICLE_CHAPTER_MODEL": "m3",
        }
        with self.assertRaises(GateError) as ctx:
            G.require_live_env(config)
        self.assertIn("credentials", str(ctx.exception))

    def test_live_provider_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from gate_runtime import load_env_file

            provider = G.require_live_env(load_env_file(live_env(Path(tmp))))
        self.assertEqual(provider["chapter_model"], "fixture-chapter")
        self.assertFalse(provider["fixture_mode"])


class BrowserManifestTests(unittest.TestCase):
    def test_missing_manifest_fields_fail_closed(self) -> None:
        with self.assertRaises(GateError):
            G.validate_browser_manifest(None)
        with self.assertRaises(GateError):
            G.validate_browser_manifest({"schema": "wrong"})
        with self.assertRaises(GateError):
            G.validate_browser_manifest(
                {"schema": G.BROWSER_MANIFEST_SCHEMA, "streams": []}
            )
        with self.assertRaises(GateError):
            G.validate_browser_manifest(
                {
                    "schema": G.BROWSER_MANIFEST_SCHEMA,
                    "streams": [
                        {
                            "stream_id": "x",
                            "catalog_sha": "short",
                            "first_unit_id": "ru_0",
                            "unit_count": 1,
                            "group_count": 1,
                        }
                    ],
                }
            )

    def test_valid_manifest_passes(self) -> None:
        work = {
            "stream_id": "0192aaaa-bbbb-7ccc-8ddd-eeeeeeeeeeee",
            "catalog_sha": "a" * 64,
            "source_title": "Fixture",
            "unit_count": 3,
            "group_count": 1,
            "first_unit_id": "ru_" + "0" * 24,
            "event_ids": [],
        }
        manifest = G.build_browser_manifest([work], base_url=None)
        self.assertIs(G.validate_browser_manifest(manifest), manifest)
        self.assertTrue(manifest["performance"]["synthetic"])
        self.assertEqual(manifest["performance"]["target_units"], 5000)


class BoundaryTests(unittest.TestCase):
    def test_no_direct_product_writes(self) -> None:
        report = G.check_no_direct_product_writes()
        self.assertFalse(report["direct_product_writes"])

    def test_gate_project_is_prefixed(self) -> None:
        self.assertTrue(default_gate_project("r2").startswith("chronicle-gate-"))

    def test_evidence_failure_keeps_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            evidence = Evidence(directory, {"schema": "x", "result": "PENDING"})
            evidence.data["works"] = [1]
            evidence.fail("boom")
            self.assertTrue((directory / "manifest.partial.json").is_file())
            self.assertFalse((directory / "manifest.json").is_file())
            stored = json.loads((directory / "manifest.partial.json").read_text())
            self.assertEqual(stored["result"], "FAIL")


class LiveCliTests(unittest.TestCase):
    def test_live_refuses_auto_decisions_before_anything(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_gate(
                "--mode", "live",
                "--env-file", str(live_env(Path(tmp))),
                "--source-pack", str(SOURCE_PACK),
                "--evidence-dir", str(Path(tmp) / "evidence"),
                "--auto-decide",
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("auto-decide", result.stderr)

    def test_live_refuses_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_gate(
                "--mode", "live",
                "--env-file", str(live_env(Path(tmp))),
                "--source-pack", str(SOURCE_PACK),
                "--evidence-dir", str(Path(tmp) / "evidence"),
                "--execute",
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("T17", result.stderr)

    def test_live_requires_interactive_terminal(self) -> None:
        real = sys.stdin
        G.sys.stdin = mock.Mock(isatty=lambda: True)  # type: ignore[assignment]
        try:
            self.assertTrue(G.require_interactive_stdin())
        finally:
            G.sys.stdin = real  # type: ignore[assignment]
        G.sys.stdin = mock.Mock(isatty=lambda: False)  # type: ignore[assignment]
        try:
            with self.assertRaises(GateError) as ctx:
                G.require_interactive_stdin()
        finally:
            G.sys.stdin = real  # type: ignore[assignment]
        self.assertIn("interactive terminal", str(ctx.exception))

    def test_live_non_tty_pipe_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_gate(
                "--mode", "live",
                "--env-file", str(live_env(Path(tmp))),
                "--source-pack", str(SOURCE_PACK),
                "--evidence-dir", str(Path(tmp) / "evidence"),
                stdin_data="",
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("interactive terminal", result.stderr)


if __name__ == "__main__":
    unittest.main()
