"""Unit tests for Chronicle worker entrypoint helpers (no PostgreSQL).

Covers `--source-dir` / `CHRONICLE_SOURCE_DIR` resolution: an explicit
flag wins, a non-empty env enables the production revision loader, and
an unset env keeps the deterministic fake path instead of guessing.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
for path in (str(HERE), str(PERSISTENCE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import ingestion_worker as worker  # noqa: E402
from common import PersistenceError  # noqa: E402


class ScriptedModel:
    name = "unit-scripted-v1"

    def complete(self, prompt: str) -> str:
        raise AssertionError("must not be called")


class ChunkModelHookTests(unittest.TestCase):
    def test_extract_defaults_to_fake_path(self) -> None:
        runner = worker.JobRunner("postgresql://localhost/x", worker="w1")
        self.assertIsNone(runner.chunk_model)
        self.assertIsNone(runner.extraction_schema)
        self.assertIsNone(runner.allowed_predicates)
        self.assertEqual({}, runner.document_meta)

    def test_chunk_model_hook_is_accepted(self) -> None:
        runner = worker.JobRunner(
            "postgresql://localhost/x", worker="w1", chunk_model=ScriptedModel()
        )
        self.assertIsInstance(runner.chunk_model, ScriptedModel)

    def test_chunk_model_must_expose_protocol(self) -> None:
        with self.assertRaises(PersistenceError):
            worker.JobRunner("postgresql://localhost/x", worker="w1", chunk_model=object())
        incomplete = ScriptedModel()
        incomplete.name = None  # type: ignore[assignment]
        with self.assertRaises(PersistenceError):
            worker.JobRunner(
                "postgresql://localhost/x", worker="w1", chunk_model=incomplete
            )


class SourceDirTests(unittest.TestCase):
    def test_explicit_flag_wins_over_env(self) -> None:
        with mock.patch.dict(os.environ, {"CHRONICLE_SOURCE_DIR": "/env/dir"}):
            resolved = worker.source_dir_from_env("/flag/dir")
        self.assertEqual(resolved, Path("/flag/dir"))

    def test_env_enables_production_loader(self) -> None:
        with mock.patch.dict(os.environ, {"CHRONICLE_SOURCE_DIR": " /data/src "}):
            resolved = worker.source_dir_from_env(None)
        self.assertEqual(resolved, Path("/data/src"))

    def test_unset_env_keeps_fake_path(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHRONICLE_SOURCE_DIR", None)
            self.assertIsNone(worker.source_dir_from_env(None))

    def test_parser_defaults_to_unset_source_dir(self) -> None:
        args = worker.build_parser().parse_args(["--worker-id", "w1"])
        self.assertIsNone(args.source_dir)


if __name__ == "__main__":
    unittest.main()
