"""Pure-unit regressions for C2-R1 chapter stage wiring (no PostgreSQL).

Covers two live findings from the T19 first-round run without needing a
database: the ``chapter_failed`` log event must carry the persisted error
message (it previously read a checkpoint key that never exists, so every
failure logged ``error: None``), and the joint chapter provider must
honor ``CHRONICLE_MODEL_TIMEOUT_SECONDS`` instead of silently keeping
the code default.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
for path in (HERE, PERSISTENCE):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

import chapter_stage as S  # noqa: E402
import model_provider as M  # noqa: E402
from common import PersistenceError  # noqa: E402


def live_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        "CHRONICLE_MODEL_ENDPOINT": "https://gateway.example/v1/responses",
        "CHRONICLE_CHAPTER_MODEL": "live-chapter-model",
    }
    if extra:
        env.update(extra)
    return env


class ChapterErrorMessageTests(unittest.TestCase):
    def test_dict_error_message_used(self) -> None:
        result = {"accepted": False, "error": {"code": "x", "message": "real cause"}}
        self.assertEqual("real cause", S._chapter_error_message(result))

    def test_string_error_used(self) -> None:
        self.assertEqual("boom", S._chapter_error_message({"error": "boom"}))

    def test_missing_error_falls_back(self) -> None:
        for result in ({}, {"error": None}, {"error": {}}, {"error": "  "}, "not-a-dict"):
            self.assertEqual(
                "chapter extraction failed closed",
                S._chapter_error_message(result),  # type: ignore[arg-type]
                msg=repr(result),
            )


class ChapterModelTimeoutTests(unittest.TestCase):
    def test_default_timeout_is_code_default(self) -> None:
        model = S.chapter_model_from_env(live_env())
        self.assertEqual(M.DEFAULT_MODEL_TIMEOUT_SECONDS, model.timeout_seconds)

    def test_configured_timeout_reaches_chapter_provider(self) -> None:
        model = S.chapter_model_from_env(
            live_env({"CHRONICLE_MODEL_TIMEOUT_SECONDS": "45.5"})
        )
        self.assertEqual("live-chapter-model", model.name)
        self.assertEqual(45.5, model.timeout_seconds)

    def test_invalid_timeout_fails_closed(self) -> None:
        for bad in ("0", "-3", "not-a-number"):
            with self.assertRaises(PersistenceError, msg=bad):
                S.chapter_model_from_env(
                    live_env({"CHRONICLE_MODEL_TIMEOUT_SECONDS": bad})
                )

    def test_timeout_helper_accepts_mapping_or_process_env(self) -> None:
        self.assertEqual(
            M.DEFAULT_MODEL_TIMEOUT_SECONDS, M.timeout_from_env({})
        )
        self.assertEqual(12.5, M.timeout_from_env(
            {"CHRONICLE_MODEL_TIMEOUT_SECONDS": "12.5"}))


class ChapterModelVersionTests(unittest.TestCase):
    def test_environment_selection_keeps_worker_and_strict_format_together(self) -> None:
        for name, expected in (
            ("live-chapter-model", "0.3"),
            ("fixture:person-state-chapter", "0.3"),
            ("fixture:reading-chapter", "0.2"),
            ("fixture:chapter", "0.1"),
        ):
            with self.subTest(name=name):
                model = S.chapter_model_from_env(
                    live_env({"CHRONICLE_CHAPTER_MODEL": name})
                )
                self.assertEqual(expected, S.candidate_version_for_model(model))
                self.assertEqual(
                    expected,
                    model.text_format["schema"]["properties"]["version"]["const"],
                )

    def test_explicit_factory_version_wins_over_the_model_name(self) -> None:
        for version in ("0.1", "0.2", "0.3"):
            with self.subTest(version=version):
                model = M.build_chapter_model(
                    "fixture:chapter",
                    "https://gateway.example/v1/responses",
                    candidate_version=version,
                )
                self.assertEqual(version, S.candidate_version_for_model(model))

    def test_unsupported_declared_version_fails_closed(self) -> None:
        with self.assertRaisesRegex(PersistenceError, "unsupported candidate version"):
            S.candidate_version_for_model(
                SimpleNamespace(name="fixture:chapter", candidate_version="9.9")
            )


if __name__ == "__main__":
    unittest.main()
