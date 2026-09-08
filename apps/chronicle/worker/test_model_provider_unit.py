"""Unit contracts for the C1-T13 deployment model provider (no network)."""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock
from urllib import error

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
for path in (str(HERE), str(PERSISTENCE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import model_provider  # noqa: E402
from common import PersistenceError  # noqa: E402


class FakeResponse:
    def __init__(self, payload: object, *, content_length: int | None = None) -> None:
        self.raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.headers = Message()
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        return self.raw if amount < 0 else self.raw[:amount]


class ResponsesHTTPModelTests(unittest.TestCase):
    def test_posts_model_input_bearer_auth_and_product_user_agent(self) -> None:
        provider = model_provider.ResponsesHTTPModel(
            name="reader-v1",
            endpoint="https://gateway.example/v1/responses",
            api_key="secret-token",
        )
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["timeout"] = timeout
            captured["headers"] = dict(req.header_items())
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"output_text": "现代中文"})

        with mock.patch.object(model_provider.request, "urlopen", side_effect=fake_urlopen):
            self.assertEqual("现代中文", provider.complete("原文"))

        self.assertEqual("https://gateway.example/v1/responses", captured["url"])
        self.assertEqual(600.0, captured["timeout"])
        self.assertEqual({"model": "reader-v1", "input": "原文"}, captured["body"])
        self.assertEqual("Bearer secret-token", captured["headers"]["Authorization"])
        self.assertEqual(
            model_provider.MODEL_HTTP_USER_AGENT,
            captured["headers"]["User-agent"],
        )
        self.assertFalse(captured["headers"]["User-agent"].startswith("Python-urllib"))

    def test_structured_text_format_is_sent_without_changing_text_boundary(self) -> None:
        text_format = {
            "type": "json_schema",
            "name": "example",
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["value"],
                "properties": {"value": {"type": "string"}},
            },
            "strict": True,
        }
        provider = model_provider.ResponsesHTTPModel(
            name="extract-v1",
            endpoint="https://gateway.example/v1/responses",
            text_format=text_format,
        )
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"output_text": '{"value":"ok"}'})

        with mock.patch.object(model_provider.request, "urlopen", side_effect=fake_urlopen):
            self.assertEqual('{"value":"ok"}', provider.complete("source"))
        self.assertEqual(text_format, captured["body"]["text"]["format"])
        self.assertEqual("source", captured["body"]["input"])

    def test_nested_output_text_is_supported(self) -> None:
        provider = model_provider.ResponsesHTTPModel(
            name="extract-v1", endpoint="http://model.local/responses"
        )
        payload = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "第一段"},
                        {"type": "refusal", "refusal": "ignored"},
                        {"type": "output_text", "text": "第二段"},
                    ],
                }
            ]
        }
        with mock.patch.object(
            model_provider.request, "urlopen", return_value=FakeResponse(payload)
        ):
            self.assertEqual("第一段第二段", provider.complete("prompt"))

    def test_invalid_endpoint_or_embedded_credentials_fail_closed(self) -> None:
        with self.assertRaises(PersistenceError):
            model_provider.ResponsesHTTPModel(name="x", endpoint="file:///tmp/model")
        with self.assertRaises(PersistenceError):
            model_provider.ResponsesHTTPModel(
                name="x", endpoint="https://user:password@example.test/responses"
            )
        with self.assertRaises(PersistenceError):
            model_provider.ResponsesHTTPModel(
                name="x", endpoint="https://example.test/responses", text_format="bad"
            )

    def test_http_error_does_not_echo_body_or_key(self) -> None:
        provider = model_provider.ResponsesHTTPModel(
            name="x", endpoint="https://example.test/responses", api_key="super-secret"
        )
        exc = error.HTTPError(
            provider.endpoint,
            401,
            "Unauthorized super-secret",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"super-secret prompt contents"}'),
        )
        with mock.patch.object(model_provider.request, "urlopen", side_effect=exc):
            with self.assertRaises(model_provider.ModelProviderError) as caught:
                provider.complete("private source text")
        text = str(caught.exception)
        self.assertEqual("model endpoint returned HTTP 401", text)
        self.assertNotIn("super-secret", text)
        self.assertNotIn("private source text", text)

    def test_declared_or_actual_oversize_response_is_rejected(self) -> None:
        provider = model_provider.ResponsesHTTPModel(
            name="x", endpoint="https://example.test/responses", max_response_bytes=16
        )
        with mock.patch.object(
            model_provider.request,
            "urlopen",
            return_value=FakeResponse({"output_text": "x"}, content_length=99),
        ):
            with self.assertRaisesRegex(
                model_provider.ModelProviderError, "size limit"
            ):
                provider.complete("prompt")

        big = FakeResponse({"output_text": "x" * 100})
        with mock.patch.object(model_provider.request, "urlopen", return_value=big):
            with self.assertRaisesRegex(
                model_provider.ModelProviderError, "size limit"
            ):
                provider.complete("prompt")

    def test_invalid_json_or_missing_text_is_rejected(self) -> None:
        provider = model_provider.ResponsesHTTPModel(
            name="x", endpoint="https://example.test/responses"
        )

        class BadJson(FakeResponse):
            def __init__(self):
                self.raw = b"not-json"
                self.headers = Message()

        with mock.patch.object(
            model_provider.request, "urlopen", return_value=BadJson()
        ):
            with self.assertRaisesRegex(model_provider.ModelProviderError, "invalid JSON"):
                provider.complete("prompt")
        with mock.patch.object(
            model_provider.request, "urlopen", return_value=FakeResponse({"output": []})
        ):
            with self.assertRaisesRegex(model_provider.ModelProviderError, "no output text"):
                provider.complete("prompt")


class EnvironmentTests(unittest.TestCase):
    ENV_KEYS = {
        "CHRONICLE_MODEL_ENDPOINT",
        "CHRONICLE_MODEL_API_KEY",
        "CHRONICLE_MODEL_TIMEOUT_SECONDS",
        "CHRONICLE_EXTRACTION_MODEL",
        "CHRONICLE_PRESENTATION_MODEL",
    }

    def clean_env(self, values: dict[str, str] | None = None):
        patch = {key: "" for key in self.ENV_KEYS}
        if values:
            patch.update(values)
        return mock.patch.dict(os.environ, patch, clear=False)

    def test_no_models_preserves_old_worker_path(self) -> None:
        with self.clean_env():
            extraction, presentation = model_provider.models_from_env()
        self.assertIsNone(extraction)
        self.assertIsNone(presentation)

    def test_models_are_independently_configured(self) -> None:
        with self.clean_env(
            {
                "CHRONICLE_MODEL_ENDPOINT": "https://gateway.example/v1/responses",
                "CHRONICLE_MODEL_API_KEY": "token",
                "CHRONICLE_MODEL_TIMEOUT_SECONDS": "45.5",
                "CHRONICLE_EXTRACTION_MODEL": "extract-model",
            }
        ):
            extraction, presentation = model_provider.models_from_env()
        self.assertIsNotNone(extraction)
        assert extraction is not None
        self.assertEqual("extract-model", extraction.name)
        self.assertEqual(45.5, extraction.timeout_seconds)
        self.assertEqual("token", extraction.api_key)
        self.assertIsInstance(extraction.text_format, dict)
        assert extraction.text_format is not None
        self.assertEqual("json_schema", extraction.text_format["type"])
        self.assertTrue(extraction.text_format["strict"])
        self.assertEqual("0.1", extraction.text_format["schema"]["properties"]["schema_version"]["const"])
        self.assertIsNone(presentation)

    def test_presentation_model_sends_its_own_strict_contract(self) -> None:
        with self.clean_env(
            {
                "CHRONICLE_MODEL_ENDPOINT": "https://gateway.example/v1/responses",
                "CHRONICLE_PRESENTATION_MODEL": "reader-model",
            }
        ):
            extraction, presentation = model_provider.models_from_env()
        self.assertIsNone(extraction)
        self.assertIsNotNone(presentation)
        assert presentation is not None
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"output_text": "{}"})

        with mock.patch.object(model_provider.request, "urlopen", side_effect=fake_urlopen):
            self.assertEqual("{}", presentation.complete("reader context"))
        fmt = captured["body"]["text"]["format"]
        self.assertEqual("reader-model", captured["body"]["model"])
        self.assertEqual("json_schema", fmt["type"])
        self.assertTrue(fmt["strict"])
        self.assertEqual("chronicle.reader-presentation", fmt["schema"]["properties"]["schema"]["const"])
        self.assertEqual(
            {"schema", "version", "target_kind", "canonical_id", "language", "blocks"},
            set(fmt["schema"]["required"]),
        )
        self.assertNotIn("schema_version", fmt["schema"]["properties"])

    def test_configured_model_requires_endpoint_and_valid_timeout(self) -> None:
        with self.clean_env({"CHRONICLE_PRESENTATION_MODEL": "reader"}):
            with self.assertRaisesRegex(PersistenceError, "MODEL_ENDPOINT"):
                model_provider.models_from_env()
        with self.clean_env(
            {
                "CHRONICLE_PRESENTATION_MODEL": "reader",
                "CHRONICLE_MODEL_ENDPOINT": "http://model.local/responses",
                "CHRONICLE_MODEL_TIMEOUT_SECONDS": "0",
            }
        ):
            with self.assertRaisesRegex(PersistenceError, "TIMEOUT"):
                model_provider.models_from_env()


class ChapterProviderTests(unittest.TestCase):
    def test_legacy_default_response_cap_stays_2mib(self) -> None:
        self.assertEqual(2 * 1024 * 1024, model_provider.DEFAULT_MAX_RESPONSE_BYTES)
        provider = model_provider.ResponsesHTTPModel(
            name="extract-v1", endpoint="https://gateway.example/v1/responses"
        )
        self.assertEqual(2 * 1024 * 1024, provider.max_response_bytes)
        self.assertIsNone(provider.max_output_tokens)

    def test_chapter_factory_applies_dedicated_4mib_cap(self) -> None:
        self.assertEqual(
            4 * 1024 * 1024, model_provider.DEFAULT_CHAPTER_MAX_RESPONSE_BYTES
        )
        provider = model_provider.build_chapter_model(
            "chapter-live", "https://gateway.example/v1/responses"
        )
        self.assertEqual(4 * 1024 * 1024, provider.max_response_bytes)
        self.assertEqual(
            model_provider.DEFAULT_CHAPTER_MAX_OUTPUT_TOKENS,
            provider.max_output_tokens,
        )
        legacy = model_provider.ResponsesHTTPModel(
            name="extract-v1", endpoint="https://gateway.example/v1/responses"
        )
        self.assertEqual(2 * 1024 * 1024, legacy.max_response_bytes)

    def test_chapter_request_carries_joint_schema_and_output_budget(self) -> None:
        try:
            from extraction_model_schema import chapter_candidate_text_format
        except ImportError:
            from .extraction_model_schema import (  # type: ignore[no-redef]
                chapter_candidate_text_format,
            )
        provider = model_provider.build_chapter_model(
            "chapter-live", "https://gateway.example/v1/responses"
        )
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"status": "completed", "output_text": '{"ok":true}'})

        with mock.patch.object(model_provider.request, "urlopen", side_effect=fake_urlopen):
            self.assertEqual('{"ok":true}', provider.complete("chapter source"))

        body = captured["body"]
        self.assertEqual("chapter-live", body["model"])
        self.assertEqual(65536, body["max_output_tokens"])
        self.assertEqual(
            model_provider.DEFAULT_CHAPTER_MAX_OUTPUT_TOKENS, body["max_output_tokens"]
        )
        fmt = body["text"]["format"]
        self.assertEqual("chronicle_chapter_candidate", fmt["name"])
        self.assertTrue(fmt["strict"])
        dumped = json.dumps(fmt["schema"])
        self.assertIn("chronicle.chapter-candidate", dumped)
        self.assertIn("translation", dumped)
        self.assertIn("record_sources", dumped)
        for forbidden in ("anchor_id", "canonical_id", "request_fingerprint", '"start"', '"end"'):
            self.assertNotIn(forbidden, dumped)
        self.assertEqual(fmt, chapter_candidate_text_format())

    def test_legacy_request_shape_is_unchanged_without_output_budget(self) -> None:
        provider = model_provider.ResponsesHTTPModel(
            name="reader-v1", endpoint="https://gateway.example/v1/responses"
        )
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"output_text": "ok"})

        with mock.patch.object(model_provider.request, "urlopen", side_effect=fake_urlopen):
            self.assertEqual("ok", provider.complete("prompt"))
        self.assertNotIn("max_output_tokens", captured["body"])
        self.assertNotIn("text", captured["body"])

    def test_invalid_output_budget_fails_closed(self) -> None:
        for bad in (0, -1, True, "65536"):
            with self.subTest(budget=bad):
                with self.assertRaises(PersistenceError):
                    model_provider.ResponsesHTTPModel(
                        name="chapter",
                        endpoint="https://example.test/responses",
                        max_output_tokens=bad,
                    )

    def test_incomplete_length_with_partial_text_is_not_completion(self) -> None:
        provider = model_provider.ResponsesHTTPModel(
            name="chapter", endpoint="https://example.test/responses"
        )
        payload = {
            "status": "incomplete",
            "incomplete_details": {"reason": "length"},
            "output_text": '{"schema":"chronicle.chapter-candidate"',
        }
        with mock.patch.object(
            model_provider.request, "urlopen", return_value=FakeResponse(payload)
        ):
            with self.assertRaisesRegex(
                model_provider.ModelProviderError, "did not complete"
            ):
                provider.complete("chapter source")

    def test_max_output_tokens_reason_is_not_completion(self) -> None:
        provider = model_provider.ResponsesHTTPModel(
            name="chapter", endpoint="https://example.test/responses"
        )
        payload = {
            "status": "completed",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output_text": '{"partial":true}',
        }
        with mock.patch.object(
            model_provider.request, "urlopen", return_value=FakeResponse(payload)
        ):
            with self.assertRaisesRegex(
                model_provider.ModelProviderError, "max_output_tokens"
            ):
                provider.complete("chapter source")

    def test_failed_status_is_not_completion(self) -> None:
        provider = model_provider.ResponsesHTTPModel(
            name="chapter", endpoint="https://example.test/responses"
        )
        payload = {"status": "failed", "output_text": '{"partial":true}'}
        with mock.patch.object(
            model_provider.request, "urlopen", return_value=FakeResponse(payload)
        ):
            with self.assertRaisesRegex(
                model_provider.ModelProviderError, "did not complete"
            ):
                provider.complete("chapter source")

    def test_response_level_refusal_is_rejected_without_leaking_prompt(self) -> None:
        provider = model_provider.ResponsesHTTPModel(
            name="chapter",
            endpoint="https://example.test/responses",
            api_key="super-secret",
        )
        payload = {"refusal": "declined to generate"}
        with mock.patch.object(
            model_provider.request, "urlopen", return_value=FakeResponse(payload)
        ):
            with self.assertRaises(model_provider.ModelProviderError) as caught:
                provider.complete("private chapter source text")
        text = str(caught.exception)
        self.assertIn("refused", text)
        self.assertNotIn("super-secret", text)
        self.assertNotIn("private chapter source text", text)
        self.assertNotIn("declined to generate", text)

    def test_completed_status_with_text_still_succeeds(self) -> None:
        provider = model_provider.ResponsesHTTPModel(
            name="chapter", endpoint="https://example.test/responses"
        )
        payload = {"status": "completed", "output_text": '{"ok":true}'}
        with mock.patch.object(
            model_provider.request, "urlopen", return_value=FakeResponse(payload)
        ):
            self.assertEqual('{"ok":true}', provider.complete("prompt"))


if __name__ == "__main__":
    unittest.main()
