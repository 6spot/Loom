#!/usr/bin/env python3
"""Scoped offline tests for the C2-R2-T16 second-round reading gate.

Covers the gate decision/boundary logic owned by this task, without a live
stack:

- the deterministic fixture candidate is grounded verbatim in the planned
  chapter text and carries one resolved event span the browser can exercise;
- the candidate passes the owning T01 reading validator;
- the fixture/live provider guards fail closed (fixture packs in fixture mode,
  live model in live mode, endpoint credentials, missing joint model);
- the browser fixture manifest is required and must be complete (streams,
  content versions and the synthetic 5,000/1,000 scale set), so a missing
  fixture/scale/manifest fails the harness instead of silently passing;
- the orchestrator carries no direct product-table writes;
- the live entry refuses automatic decisions, non-interactive review and
  execution;
- the isolated Compose project name is prefixed so a gate never touches an
  operator deployment;
- the synthetic scale seed result marker is parsed fail-closed.

The real Rust/Python/PG + browser chain is exercised by the gate itself
(fixture mode); it is not faked here.

Run::

    python3 -m unittest discover -s apps/chronicle/acceptance \
        -p 'test_second_round_gate.py' -v
"""

from __future__ import annotations

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
from reading_scale_fixture import parse_scale_result  # noqa: E402

import chapter_contract  # noqa: E402
import chapter_plan  # noqa: E402
import fixture_model  # noqa: E402
import reading_contract  # noqa: E402

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


def tiny_request() -> dict:
    import hashlib

    revision_id = uuid.uuid5(uuid.NAMESPACE_URL, "c2r2-test")
    digest = hashlib.sha256(TINY_TEXT.encode("utf-8")).hexdigest()
    locator = {
        "revision_id": str(revision_id),
        "source_sha256": digest,
        "normalized_sha256": digest,
    }
    plan = chapter_plan.plan_chapters(
        TINY_TEXT, locator, "tiny.md", limits=chapter_contract.ChapterLimits()
    )
    request = chapter_plan.build_chapter_request(
        plan, 0, TINY_TEXT, limits=chapter_contract.ChapterLimits()
    )
    request["normalized_sha256"] = hashlib.sha256(
        request["normalized_text"].encode("utf-8")
    ).hexdigest()
    return request


def run_gate(*args: str, stdin_data: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE), *args],
        cwd=REPO,
        text=True,
        capture_output=True,
        input=stdin_data,
    )


class FixtureConstructionTests(unittest.TestCase):
    def test_grounded_spec_is_bound_to_request(self) -> None:
        request = tiny_request()
        spec = G.grounded_spec(request, "Fixture書")
        self.assertEqual(spec["chapter_id"], request["chapter_id"])
        self.assertEqual(spec["revision_id"], request["revision_id"])
        for entity in spec["entities"]:
            self.assertIn(entity["mention"], request["normalized_text"])

    def test_fixture_candidate_passes_owning_validator(self) -> None:
        request = tiny_request()
        candidate = fixture_model.build_reading_chapter_candidate(
            request, G.grounded_spec(request, "Fixture書")
        )
        G.add_resolved_span(candidate, request)
        report = reading_contract.validate_reading_annotations(request, candidate)
        self.assertTrue(
            report.get("passed"),
            msg="; ".join(reading_contract.flatten_reading_errors(report)),
        )
        spans = [
            span
            for unit in candidate["reading"]["units"]
            for span in unit.get("event_spans", [])
        ]
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0]["span_id"], "es_001")
        self.assertEqual(spans[0]["status"], "resolved")
        self.assertTrue(spans[0]["target_ref"])

    def test_fixture_mode_refuses_fixture_packs(self) -> None:
        with self.assertRaises(GateError):
            G.require_fixture_env({"CHRONICLE_MODEL_FIXTURE_PACK": "/tmp/x.json"})
        with self.assertRaises(GateError):
            G.require_fixture_env({"CHRONICLE_CHAPTER_FIXTURE_PACK": "/tmp/x.json"})
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


def sample_work() -> dict:
    return {
        "stream_id": "0192aaaa-bbbb-7ccc-8ddd-eeeeeeeeeeee",
        "catalog_sha": "a" * 64,
        "source_title": "Fixture",
        "unit_count": 3,
        "group_count": 1,
        "first_unit_id": "ru_" + "0" * 24,
        "event_ids": ["0192aaaa-bbbb-7ccc-8ddd-ffffffffffff"],
    }


def sample_scale() -> dict:
    return {
        "synthetic": True,
        "stream_id": "0192aaaa-bbbb-7ccc-8ddd-000000000000",
        "catalog_sha": "b" * 64,
        "unit_count": 5000,
        "group_count": 1000,
        "first_unit_id": "ru_" + "1" * 24,
        "last_unit_id": "ru_" + "2" * 24,
    }


def sample_negatives() -> list:
    return [
        {
            "kind": kind,
            "stream_id": sample_scale()["stream_id"],
            "catalog_sha": sample_scale()["catalog_sha"],
            "unit_id": "ru_" + "3" * 24,
        }
        for kind in ("unknown_time", "missing_context", "missing_role")
    ]


class BrowserManifestTests(unittest.TestCase):
    def _manifest(self, **overrides) -> dict:
        manifest = {
            "schema": G.BROWSER_MANIFEST_SCHEMA,
            "version": G.BROWSER_MANIFEST_VERSION,
            "streams": [sample_work()],
            "versions": [
                {"label": "v1", "catalog_sha": "a" * 64, "stream_id": sample_work()["stream_id"]}
            ],
            "negatives": sample_negatives(),
            "scale": sample_scale(),
        }
        manifest.update(overrides)
        return manifest

    def test_valid_manifest_passes(self) -> None:
        manifest = self._manifest()
        self.assertIs(G.validate_browser_manifest(manifest), manifest)

    def test_missing_manifest_fields_fail_closed(self) -> None:
        for broken in (
            None,
            {"schema": "wrong"},
            self._manifest(streams=[]),
            self._manifest(scale=None),
            self._manifest(scale={**sample_scale(), "unit_count": 10}),
            self._manifest(versions=[]),
            self._manifest(negatives=[]),
            self._manifest(negatives=sample_negatives()[:2]),
        ):
            with self.assertRaises(GateError):
                G.validate_browser_manifest(broken)

    def test_short_catalog_fails(self) -> None:
        work = {**sample_work(), "catalog_sha": "short"}
        with self.assertRaises(GateError):
            G.validate_browser_manifest(self._manifest(streams=[work]))


class TimeAndRoleContractTests(unittest.TestCase):
    def _unknown(self) -> dict:
        return {
            "mode": "unknown",
            "status": "unknown",
            "event_refs": [],
            "from_block_id": None,
            "observations": [],
            "year_key": "unknown",
            "period_key": "unknown",
            "year_label": None,
            "period_label": "时间未明确",
            "precision": "unknown",
            "continues_previous": False,
        }

    def test_unknown_time_passes(self) -> None:
        G.assert_time_contract(self._unknown())

    def test_events_without_refs_rejected(self) -> None:
        with self.assertRaises(GateError):
            G.assert_time_contract(
                {**self._unknown(), "mode": "events", "status": "resolved"}
            )

    def test_unknown_with_refs_rejected(self) -> None:
        with self.assertRaises(GateError):
            G.assert_time_contract({**self._unknown(), "event_refs": ["evt_1"]})

    def test_entity_without_role_is_valid(self) -> None:
        entity = {
            "entity_ref": "scale_ent_1",
            "name": "合成人物",
            "canonical_id": None,
            "kind": "person",
            "importance": "primary",
            "source_anchor_ids": [],
            "event_roles": [],
        }
        self.assertEqual(
            reading_contract.validate_reading_dto("context_entity_view", entity), []
        )


class BoundaryTests(unittest.TestCase):
    def test_no_direct_product_writes(self) -> None:
        report = G.check_no_direct_product_writes()
        self.assertFalse(report["direct_product_writes"])

    def test_scale_fixture_scope_handoff_recorded(self) -> None:
        import reading_scale_fixture

        handoff = reading_scale_fixture.SCOPE_HANDOFF
        self.assertIn("reading_scale_fixture", (HERE / "reading_scale_fixture.py").name)
        self.assertIn("second_round_gate.py", handoff)
        task_note = (
            REPO
            / "docs/tasks/chronicle/second-round/T16-reading-automated-gate.md"
        ).read_text(encoding="utf-8")
        self.assertIn("reading_scale_fixture.py", task_note)
        self.assertIn("File scope coordination", task_note)
        acceptance_doc = (REPO / "apps/chronicle/docs/reading-acceptance.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("reading_scale_fixture.py", acceptance_doc)

    def test_scale_fixture_has_no_raw_writes(self) -> None:
        import reading_scale_fixture

        text = (HERE / "reading_scale_fixture.py").read_text(encoding="utf-8")
        for token in (
            "INSERT INTO",
            "UPDATE chronicle.",
            "DELETE FROM",
            "CREATE TABLE",
            "DROP TABLE",
            "ALTER TABLE",
        ):
            self.assertNotIn(token, text, msg=f"scale fixture carries raw write {token!r}")
        self.assertIn("reading_store.persist_reading_stream", reading_scale_fixture.SEED_SCRIPT)
        self.assertIn(
            "chapter_store.record_accepted_chapter_fenced",
            reading_scale_fixture.SEED_SCRIPT,
        )

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

    def test_scale_result_marker_parses(self) -> None:
        stdout = 'noise\nGATE_SCALE_RESULT={"stream_id": "s", "unit_count": 5000}\n'
        self.assertEqual(parse_scale_result(stdout)["unit_count"], 5000)
        with self.assertRaises(RuntimeError):
            parse_scale_result("no marker here")


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
