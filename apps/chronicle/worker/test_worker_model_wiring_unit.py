"""Production entrypoint wiring for C1-T13 model providers (no PostgreSQL)."""

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


class ScriptedProvider:
    def __init__(self, name: str) -> None:
        self.name = name

    def complete(self, prompt: str) -> str:
        raise AssertionError("entrypoint wiring test must not call the model")


class ProductionModelWiringTests(unittest.TestCase):
    def test_main_passes_independent_models_to_run_forever(self) -> None:
        extraction = ScriptedProvider("extract-live")
        presentation = ScriptedProvider("reader-live")
        env = dict(os.environ)
        env.pop("CHRONICLE_SOURCE_DIR", None)
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
            worker.model_provider,
            "models_from_env",
            return_value=(extraction, presentation),
        ) as models, mock.patch.object(
            worker, "install_shutdown_handlers"
        ), mock.patch.object(
            worker, "run_forever", return_value={}
        ) as run:
            result = worker.main(
                [
                    "--database-url",
                    "postgresql://localhost/chronicle",
                    "--worker-id",
                    "worker-model-wiring",
                    "--max-jobs",
                    "0",
                ]
            )

        self.assertEqual(0, result)
        models.assert_called_once_with()
        kwargs = run.call_args.kwargs
        self.assertIs(extraction, kwargs["chunk_model"])
        self.assertIs(presentation, kwargs["presentation_model"])
        self.assertIsNone(kwargs["revision_source"])


if __name__ == "__main__":
    unittest.main()
