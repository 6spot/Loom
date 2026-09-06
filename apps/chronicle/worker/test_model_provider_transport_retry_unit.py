"""Regression tests for Chronicle model-provider transient retry semantics."""

from __future__ import annotations

import json
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


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.headers = Message()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        return self.raw if amount < 0 else self.raw[:amount]


class ModelProviderTransportRetryTests(unittest.TestCase):
    def test_transport_failure_retries_with_full_timeout_per_attempt(self) -> None:
        provider = model_provider.ResponsesHTTPModel(
            name="extract-v1",
            endpoint="https://gateway.example/v1/responses",
            timeout_seconds=600.0,
            max_attempts=3,
            retry_backoff_seconds=0,
        )
        timeouts: list[float] = []
        outcomes = iter(
            [
                error.URLError("temporary transport break"),
                FakeResponse({"output_text": "ok"}),
            ]
        )

        def fake_urlopen(req, timeout):
            del req
            timeouts.append(timeout)
            outcome = next(outcomes)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        with mock.patch.object(model_provider.request, "urlopen", side_effect=fake_urlopen):
            self.assertEqual("ok", provider.complete("prompt"))

        self.assertEqual([600.0, 600.0], timeouts)

    def test_repeated_transport_failure_uses_all_attempts_then_fails_closed(self) -> None:
        provider = model_provider.ResponsesHTTPModel(
            name="extract-v1",
            endpoint="https://gateway.example/v1/responses",
            timeout_seconds=600.0,
            max_attempts=3,
            retry_backoff_seconds=0,
        )

        with mock.patch.object(
            model_provider.request,
            "urlopen",
            side_effect=error.URLError("temporary transport break"),
        ) as urlopen:
            with self.assertRaisesRegex(
                model_provider.ModelProviderError,
                r"transient failure after 3 attempt\(s\): transport failure",
            ):
                provider.complete("prompt")

        self.assertEqual(3, urlopen.call_count)
        self.assertEqual(
            [600.0, 600.0, 600.0],
            [call.kwargs["timeout"] for call in urlopen.call_args_list],
        )

    def test_non_transient_http_error_does_not_retry(self) -> None:
        provider = model_provider.ResponsesHTTPModel(
            name="extract-v1",
            endpoint="https://gateway.example/v1/responses",
            timeout_seconds=600.0,
            max_attempts=3,
            retry_backoff_seconds=0,
        )
        response_error = error.HTTPError(
            provider.endpoint,
            400,
            "Bad Request",
            hdrs=None,
            fp=None,
        )

        with mock.patch.object(
            model_provider.request,
            "urlopen",
            side_effect=response_error,
        ) as urlopen:
            with self.assertRaisesRegex(
                model_provider.ModelProviderError,
                "model endpoint returned HTTP 400",
            ):
                provider.complete("prompt")

        self.assertEqual(1, urlopen.call_count)


if __name__ == "__main__":
    unittest.main()
