"""Retry/deadline contracts for Chronicle's production model HTTP boundary."""

from __future__ import annotations

import io
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
    def __init__(self, text: str) -> None:
        self.raw = ("{\"output_text\":\"" + text + "\"}").encode("utf-8")
        self.headers = Message()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        return self.raw if amount < 0 else self.raw[:amount]


def http_error(endpoint: str, code: int) -> error.HTTPError:
    return error.HTTPError(
        endpoint,
        code,
        "gateway detail must not leak",
        hdrs=None,
        fp=io.BytesIO(b'{"error":"private provider detail"}'),
    )


class ModelProviderRetryTests(unittest.TestCase):
    def test_transient_524_retries_and_succeeds_within_total_budget(self) -> None:
        provider = model_provider.ResponsesHTTPModel(
            name="extract-v1",
            endpoint="https://gateway.example/v1/responses",
            timeout_seconds=600,
            max_attempts=3,
            retry_backoff_seconds=0,
        )
        seen_timeouts: list[float] = []
        outcomes = [
            http_error(provider.endpoint, 524),
            http_error(provider.endpoint, 524),
            FakeResponse("ok"),
        ]

        def fake_urlopen(req, timeout):
            seen_timeouts.append(float(timeout))
            outcome = outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        with mock.patch.object(model_provider.request, "urlopen", side_effect=fake_urlopen):
            self.assertEqual("ok", provider.complete("source-grounded prompt"))

        self.assertEqual(3, len(seen_timeouts))
        self.assertEqual(600.0, seen_timeouts[0])
        self.assertTrue(all(0 < value <= 600.0 for value in seen_timeouts))

    def test_transient_524_fails_closed_after_bounded_attempts(self) -> None:
        provider = model_provider.ResponsesHTTPModel(
            name="extract-v1",
            endpoint="https://gateway.example/v1/responses",
            timeout_seconds=600,
            max_attempts=3,
            retry_backoff_seconds=0,
        )
        side_effect = [http_error(provider.endpoint, 524) for _ in range(3)]

        with mock.patch.object(
            model_provider.request,
            "urlopen",
            side_effect=side_effect,
        ) as mocked:
            with self.assertRaises(model_provider.ModelProviderError) as caught:
                provider.complete("private source text")

        self.assertEqual(3, mocked.call_count)
        text = str(caught.exception)
        self.assertEqual(
            "model endpoint transient failure after 3 attempt(s): HTTP 524",
            text,
        )
        self.assertNotIn("private source text", text)
        self.assertNotIn("private provider detail", text)

    def test_non_transient_401_is_not_retried(self) -> None:
        provider = model_provider.ResponsesHTTPModel(
            name="extract-v1",
            endpoint="https://gateway.example/v1/responses",
            timeout_seconds=600,
            max_attempts=3,
            retry_backoff_seconds=0,
        )

        with mock.patch.object(
            model_provider.request,
            "urlopen",
            side_effect=http_error(provider.endpoint, 401),
        ) as mocked:
            with self.assertRaises(model_provider.ModelProviderError) as caught:
                provider.complete("private source text")

        self.assertEqual(1, mocked.call_count)
        self.assertEqual("model endpoint returned HTTP 401", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
