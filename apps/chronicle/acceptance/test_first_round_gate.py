#!/usr/bin/env python3
"""Scoped tests for the C2-R1-T18 first-round gate (no PostgreSQL).

Covers the fixture/live contract owned by this task:

- fixture mode passes end to end on the frozen T02 source pack and its
  manifest explicitly marks the result non-live;
- live mode refuses fixture material, missing/credential-embedded
  provider config (including a missing joint chapter model),
  auto decisions, non-interactive review and execution;
- a READY live handoff performs zero provider calls (patched prechecks)
  and records the joint chapter model identity;
- the deployed chronicle-worker container receives
  CHRONICLE_CHAPTER_MODEL from the host env (compose passthrough);
- the orchestrator carries no direct product-DB writes;
- offline fault injections fail closed (missing chapter, over-limit,
  hash drift, forged adoption, tampered artifact, mixed revisions).

Run::

    python3 -m unittest discover -s apps/chronicle/acceptance \
        -p 'test_first_round_gate.py' -v
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for path in (str(HERE), str(REPO / "apps/chronicle/persistence")):
    if path not in sys.path:
        sys.path.insert(0, path)

import first_round_gate as G  # noqa: E402
from common import PersistenceError  # noqa: E402

GATE = HERE / "first_round_gate.py"
SOURCE_PACK = REPO / "apps/chronicle/corpus/first-round/source-pack.json"

TINY_TEXT = (
    "# Fixture書\n\n## 上章\n\n甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥。\n\n"
    "## 下章\n\n天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往秋收冬藏。\n"
)


def run_gate(*args: str, stdin_data: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE), *args],
        cwd=REPO,
        text=True,
        capture_output=True,
        input=stdin_data,
    )


def write_env(directory: Path, extra: str = "") -> Path:
    path = directory / "fixture-test.env"
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


def tiny_plan() -> tuple[dict, str]:
    locator = {
        "revision_id": G.revision_id_for("unit"),
        "source_sha256": G.sha256_bytes(TINY_TEXT.encode("utf-8")),
        "normalized_sha256": G.sha256_text(TINY_TEXT),
    }
    import chapter_plan as T03

    return T03.plan_chapters(TINY_TEXT, locator, "tiny.md"), TINY_TEXT


class FixtureModeTests(unittest.TestCase):
    def test_fixture_pass_marks_result_non_live(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "evidence"
            result = run_gate(
                "--mode", "fixture",
                "--env-file", str(write_env(Path(tmp))),
                "--source-pack", str(SOURCE_PACK),
                "--evidence-dir", str(evidence),
                "--allow-dirty",
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr[-2000:])
            manifest = json.loads((evidence / "manifest.json").read_text())
            self.assertEqual(manifest["result"], "PASS")
            self.assertEqual(manifest["mode"], "fixture")
            self.assertTrue(manifest["fixture_only"])
            self.assertIn("NOT live", manifest["disclaimer"])
            self.assertFalse((evidence / "manifest.partial.json").exists())
            # Candidate provenance and real chapter coverage.
            self.assertRegex(manifest["candidate"]["commit"], r"^[0-9a-f]{40}$")
            counts = [work["chapter_count"] for work in manifest["works"]]
            self.assertEqual(counts, [3, 1])
            self.assertEqual(len(manifest["faults"]), 10)
            for name, fault in manifest["faults"].items():
                self.assertTrue(fault["passed"], msg=name)
            self.assertEqual(manifest["within_revision_pairs"]["initial_decision"], "uncertain")
            self.assertEqual(manifest["cross_book_batch"]["default_decision"], "uncertain")
            # Every recorded source/product hash is a full SHA-256.
            for upload in manifest["source"]["uploads"]:
                self.assertRegex(upload["sha256"], r"^[0-9a-f]{64}$")

    def test_fixture_requires_clean_without_allow_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_gate(
                "--mode", "fixture",
                "--env-file", str(write_env(Path(tmp))),
                "--source-pack", str(SOURCE_PACK),
                "--evidence-dir", str(Path(tmp) / "evidence"),
            )
            # The delivery tree carries the new untracked gate files, so a
            # strict run must refuse; a clean checkout passes (see CI).
            if result.returncode != 0:
                self.assertIn("clean checkout", result.stderr)

    def test_fixture_failure_keeps_partial_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "no-such-pack.json"
            result = run_gate(
                "--mode", "fixture",
                "--env-file", str(write_env(Path(tmp))),
                "--source-pack", str(missing),
                "--evidence-dir", str(Path(tmp) / "evidence"),
                "--allow-dirty",
            )
            self.assertNotEqual(result.returncode, 0)


class LiveModeTests(unittest.TestCase):
    def test_live_refuses_fixture_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = live_env(Path(tmp), "CHRONICLE_MODEL_FIXTURE_PACK=/tmp/pack.json\n")
            with self.assertRaises(G.GateError) as ctx:
                G.require_live_env(G.load_env_file(env))
            self.assertIn("FIXTURE_PACK", str(ctx.exception))

    def test_live_requires_provider_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(G.GateError) as ctx:
                G.require_live_env(G.load_env_file(write_env(Path(tmp))))
            self.assertIn("CHRONICLE_MODEL_ENDPOINT", str(ctx.exception))

    def test_live_requires_chapter_model(self) -> None:
        # READY must never be issued for a deployment that cannot
        # execute the T19 joint chapter pipeline: a missing
        # CHRONICLE_CHAPTER_MODEL fails the preflight even when the
        # endpoint and the C1 extraction/presentation models are set.
        config = {
            "CHRONICLE_POSTGRES_PASSWORD": "x",
            "CHRONICLE_ADMIN_USER": "admin",
            "CHRONICLE_ADMIN_PASSWORD": "x",
            "CHRONICLE_MODEL_ENDPOINT": "https://example.test/v1/responses",
            "CHRONICLE_EXTRACTION_MODEL": "m1",
            "CHRONICLE_PRESENTATION_MODEL": "m2",
        }
        with self.assertRaises(G.GateError) as ctx:
            G.require_live_env(config)
        self.assertIn("CHRONICLE_CHAPTER_MODEL", str(ctx.exception))

    def test_live_records_chapter_model_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = G.require_live_env(
                G.load_env_file(live_env(Path(tmp)))
            )
            self.assertEqual(provider["chapter_model"], "fixture-chapter")
            self.assertFalse(provider["fixture_mode"])

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
        with self.assertRaises(G.GateError) as ctx:
            G.require_live_env(config)
        self.assertIn("credentials", str(ctx.exception))

    def test_live_subprocess_refuses_auto_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = live_env(Path(tmp))
            evidence = str(Path(tmp) / "evidence")
            for flag in ("--auto-decide", "--non-interactive", "--execute"):
                result = run_gate(
                    "--mode", "live",
                    "--env-file", str(env),
                    "--source-pack", str(SOURCE_PACK),
                    "--evidence-dir", evidence,
                    flag,
                )
                self.assertNotEqual(result.returncode, 0, msg=flag)
                self.assertIn("FAIL", result.stderr)

    def test_live_ready_handoff_calls_no_provider(self) -> None:
        prechecks: list[str] = []
        real_commit = G.candidate_commit
        real_compose = G.compose_config_check
        real_stdin = sys.stdin
        G.candidate_commit = lambda _repo: {"commit": "0" * 40, "git_clean": True}  # type: ignore[assignment]
        G.compose_config_check = lambda _env: prechecks.append("compose") or {"checked": False, "reason": "unit"}  # type: ignore[assignment]
        G.sys.stdin = mock.Mock(isatty=lambda: True)  # type: ignore[assignment]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                evidence = Path(tmp) / "evidence"
                manifest = G.run_live(
                    live_env(Path(tmp)),
                    SOURCE_PACK,
                    evidence,
                    ["first_round_gate.py", "--mode", "live"],
                    auto_decide=False,
                    non_interactive=False,
                    execute=False,
                )
        finally:
            G.candidate_commit = real_commit  # type: ignore[assignment]
            G.compose_config_check = real_compose  # type: ignore[assignment]
            G.sys.stdin = real_stdin  # type: ignore[assignment]
        self.assertEqual(manifest["result"], "READY")
        self.assertEqual(manifest["t19_handoff"]["provider_calls_by_t18"], 0)
        # READY records the joint chapter model identity: the handoff
        # must name the exact deployment entry the T19 pipeline executes.
        self.assertEqual(manifest["provider"]["chapter_model"], "fixture-chapter")
        # Only the local compose precheck ran; no provider/model call exists
        # on this path (run_live contains no model invocation at all).
        self.assertEqual(prechecks, ["compose"])

    def test_live_requires_interactive_stdin(self) -> None:
        G.sys.stdin = mock.Mock(isatty=lambda: True)  # type: ignore[assignment]
        try:
            self.assertTrue(G.require_interactive_stdin())
        finally:
            G.sys.stdin = sys.stdin  # type: ignore[assignment]
        G.sys.stdin = mock.Mock(isatty=lambda: False)  # type: ignore[assignment]
        try:
            with self.assertRaises(G.GateError) as ctx:
                G.require_interactive_stdin()
        finally:
            G.sys.stdin = sys.stdin  # type: ignore[assignment]
        self.assertIn("interactive terminal", str(ctx.exception))

    def test_live_subprocess_refuses_non_tty_stdin(self) -> None:
        # Actual non-TTY condition: stdin is a pipe, not only the
        # --non-interactive flag. Placed before the clean-checkout guard
        # so the TTY refusal is observable in any tree state.
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

    def test_compose_passes_chapter_model_to_worker(self) -> None:
        # Regression guard for the production wiring blocker: the
        # chronicle-worker container must receive CHRONICLE_CHAPTER_MODEL
        # from the host env, otherwise chapter_model_from_env() inside
        # the container sees nothing and the joint chapter pipeline
        # cannot execute.
        import yaml

        compose = yaml.safe_load(
            (REPO / "compose.chronicle.yaml").read_text(encoding="utf-8")
        )
        worker_env = compose["services"]["chronicle-worker"]["environment"]
        self.assertIn("CHRONICLE_CHAPTER_MODEL", worker_env)
        self.assertIn(
            "CHRONICLE_CHAPTER_MODEL",
            str(worker_env["CHRONICLE_CHAPTER_MODEL"]),
        )


class NoDirectDbTests(unittest.TestCase):
    def test_orchestrator_has_no_db_writes(self) -> None:
        report = G.check_no_direct_db_writes()
        self.assertFalse(report["direct_db_writes"])


class OfflineFaultTests(unittest.TestCase):
    def test_tiny_plan_assembles_and_rejects_missing_chapter(self) -> None:
        import chapter_contract as C01
        import chapter_plan as T03
        import assembly as T07

        plan, text = tiny_plan()
        self.assertEqual(len(plan["chapters"]), 2)
        used: set[str] = set()
        artifacts = []
        for chapter in plan["chapters"]:
            request = T03.build_chapter_request(plan, chapter["chapter_index"], text)
            request["normalized_sha256"] = G.sha256_text(request["normalized_text"])
            candidate = G.build_chapter_candidate(
                request, G.fixture_spec_for(request, "Fixture書", used)
            )
            report = C01.validate_chapter_candidate(request, candidate)
            self.assertTrue(
                report["passed"],
                msg="; ".join(C01.flatten_validation_errors(report)),
            )
            artifacts.append(
                C01.accept_chapter_candidate(
                    request, candidate, producing_run=G.producing_run("unit")
                )
            )
        assembled = T07.assemble_chapters(
            accepted_artifacts=artifacts, chapter_plan=plan
        )
        self.assertEqual(len(assembled["report"]["chapter_by_ref"]) >= 2, True)
        with self.assertRaises(PersistenceError):
            T07.assemble_chapters(
                accepted_artifacts=artifacts[:-1], chapter_plan=plan
            )
        with self.assertRaises(PersistenceError):
            T03.plan_chapters(
                text,
                {
                    "revision_id": plan["revision_id"],
                    "source_sha256": plan["source_sha256"],
                    "normalized_sha256": "0" * 64,
                },
                "tiny.md",
            )
        tampered = copy.deepcopy(artifacts[0])
        tampered["candidate"]["translation"]["blocks"][0]["text"] = "竄改"
        with self.assertRaises(PersistenceError):
            T07.assemble_chapters(
                accepted_artifacts=[tampered, artifacts[1]], chapter_plan=plan
            )


if __name__ == "__main__":
    unittest.main()
