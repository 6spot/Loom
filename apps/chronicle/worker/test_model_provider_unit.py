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
        self.assertEqual(120.0, captured["timeout"])
        self.assertEqual({"model": "reader-v1", "input": "原文"}, captured["body"])
        self.assertEqual("Bearer secret-token", captured["headers"]["Authorization"])
        self.assertEqual(
            model_provider.MODEL_HTTP_USER_AGENT,
            captured["headers"]["User-agent"],
        )
        self.assertFalse(captured["headers"]["User-agent"].startswith("Python-urllib"))

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
        env = {key: os.environ.get(key) for key in self.ENV_KEYS}
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
        self.assertIsNone(presentation)

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


if __name__ == "__main__":
    unittest.main()
