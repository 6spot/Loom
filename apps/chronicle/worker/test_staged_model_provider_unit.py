"""Real local HTTP regressions for bounded, cancellable staged requests."""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import httpx

HERE = Path(__file__).resolve().parent
for path in (HERE, HERE.parent / "persistence"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from model_provider import ModelProviderError, ResponsesHTTPModel
from chapter_stage import chapter_model_from_env


@contextmanager
def endpoint(serve):
    calls = []
    entered = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            calls.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            entered.set()
            try:
                serve(self)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1/responses", calls, entered
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def respond(payload, status=200):
    def serve(handler):
        body = json.dumps(payload, ensure_ascii=False).encode()
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    return serve


class StagedModelProviderTests(unittest.TestCase):
    def test_completed_receipt_and_single_http_attempt(self):
        value = {"status": "completed", "model": "actual-model", "output_text": "先主回到巫县。",
                 "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20,
                           "output_tokens_details": {"reasoning_tokens": 3}},
                 "output": [{"type": "reasoning", "content": "hidden-not-for-audit"}]}
        with endpoint(respond(value)) as (url, calls, _):
            model = ResponsesHTTPModel(name="requested", endpoint=url, timeout_seconds=3, max_attempts=3, max_output_tokens=123)
            raw, receipt = model.complete_with_receipt("整章原文")
        self.assertEqual(raw, value["output_text"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], {"model": "requested", "input": "整章原文", "max_output_tokens": 123})
        self.assertEqual(receipt["http_attempts"], 1)
        self.assertEqual(receipt["model"], "actual-model")
        self.assertEqual(receipt["usage"]["reasoning_tokens"], 3)
        self.assertNotIn("hidden-not-for-audit", json.dumps(receipt))
        self.assertGreater(receipt["response_bytes"], 0)
        self.assertEqual(receipt["timeout_seconds"], 3)

    def test_global_timeout_controls_transport_and_deadline_for_each_step(self):
        with endpoint(respond({"status": "completed", "output_text": "译文"})) as (url, calls, _):
            models = chapter_model_from_env({
                "CHRONICLE_CHAPTER_MODEL": "global-model",
                "CHRONICLE_MODEL_ENDPOINT": url,
                "CHRONICLE_MODEL_TIMEOUT_SECONDS": "900",
            })
            for step, slots in models.steps.items():
                with self.subTest(step=step), mock.patch.object(
                    asyncio, "wait_for", wraps=asyncio.wait_for
                ) as deadline, mock.patch.object(httpx, "AsyncClient", wraps=httpx.AsyncClient) as client:
                    _, receipt = models.model_for(step, slots[0]).complete_with_receipt("完整原文")
                    self.assertEqual(deadline.call_args.kwargs["timeout"], 900)
                    self.assertEqual(client.call_args.kwargs["timeout"], 900)
                    self.assertEqual(receipt["timeout_seconds"], 900)
            self.assertEqual(len(calls), len(models.steps))

    def test_unknown_usage_stays_null(self):
        with endpoint(respond({"status": "completed", "output_text": "译文"})) as (url, _, _):
            _, receipt = ResponsesHTTPModel(name="m", endpoint=url, timeout_seconds=3).complete_with_receipt("原文")
        self.assertIsNone(receipt["usage"])
        self.assertIsNone(receipt["model"])

    def test_incomplete_saves_partial_visible_text_without_accepting(self):
        payload = {"status": "incomplete", "output_text": "尚未完成的译文", "incomplete_details": {"reason": "max_output_tokens"}}
        with endpoint(respond(payload)) as (url, calls, _):
            with self.assertRaises(ModelProviderError) as caught:
                ResponsesHTTPModel(name="m", endpoint=url, timeout_seconds=3).complete_with_receipt("原文")
        self.assertEqual(caught.exception.raw_text, payload["output_text"])
        self.assertEqual(caught.exception.receipt["status"], "incomplete")
        self.assertEqual(caught.exception.receipt["incomplete_reason"], "max_output_tokens")
        self.assertEqual(len(calls), 1)

    def test_missing_completion_or_refusal_cannot_be_accepted(self):
        for payload in ({"output_text": "半份"},
                        {"status": "completed", "output_text": "片段", "output": [{"content": [{"type": "refusal", "refusal": "no"}]}]}):
            with self.subTest(payload=payload), endpoint(respond(payload)) as (url, _, _):
                with self.assertRaises(ModelProviderError):
                    ResponsesHTTPModel(name="m", endpoint=url, timeout_seconds=3).complete_with_receipt("原文")

    def test_http_error_does_not_echo_body_or_retry(self):
        with endpoint(respond({"error": "private-upstream-key"}, 503)) as (url, calls, _):
            with self.assertRaises(ModelProviderError) as caught:
                ResponsesHTTPModel(name="m", endpoint=url, timeout_seconds=3, max_attempts=3).complete_with_receipt("原文")
        self.assertEqual(len(calls), 1)
        self.assertNotIn("private-upstream-key", str(caught.exception) + json.dumps(caught.exception.receipt))
        self.assertEqual(caught.exception.receipt["http_status"], 503)

    def test_global_deadline_interrupts_keepalive_bytes(self):
        def trickle(handler):
            handler.send_response(200)
            handler.end_headers()
            for _ in range(100):
                handler.wfile.write(b" ")
                handler.wfile.flush()
                time.sleep(0.03)
        with endpoint(trickle) as (url, _, _):
            model = chapter_model_from_env({
                "CHRONICLE_CHAPTER_MODEL": "global-model",
                "CHRONICLE_MODEL_ENDPOINT": url,
                "CHRONICLE_MODEL_TIMEOUT_SECONDS": "0.3",
            }).model_for("repair", "executor")
            started = time.monotonic()
            with self.assertRaises(ModelProviderError) as caught:
                model.complete_with_receipt("原文")
            self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(caught.exception.receipt["status"], "timeout")
        self.assertEqual(caught.exception.receipt["timeout_seconds"], 0.3)
        self.assertIn("CHRONICLE_MODEL_TIMEOUT_SECONDS (0.3s)", str(caught.exception))
        self.assertGreater(caught.exception.receipt["response_bytes"], 0)

    def test_global_timeout_applies_while_waiting_for_headers(self):
        def silent(handler):
            time.sleep(0.6)
            respond({"status": "completed", "output_text": "迟到结果"})(handler)
        with endpoint(silent) as (url, calls, _):
            model = chapter_model_from_env({
                "CHRONICLE_CHAPTER_MODEL": "global-model",
                "CHRONICLE_MODEL_ENDPOINT": url,
                "CHRONICLE_MODEL_TIMEOUT_SECONDS": "0.3",
            }).model_for("extraction", "executor")
            with self.assertRaises(ModelProviderError) as caught:
                model.complete_with_receipt("原文")
        self.assertEqual(caught.exception.receipt["status"], "timeout")
        self.assertEqual(caught.exception.receipt["timeout_seconds"], 0.3)
        self.assertEqual(len(calls), 1)

    def test_cancellation_interrupts_wait_for_headers(self):
        def silent(handler):
            time.sleep(1)
            respond({"status": "completed", "output_text": "迟到结果"})(handler)
        with endpoint(silent) as (url, calls, entered):
            cancelled = threading.Event()
            canceller = threading.Thread(target=lambda: (entered.wait(2), cancelled.set()), daemon=True)
            canceller.start()
            started = time.monotonic()
            with self.assertRaises(ModelProviderError) as caught:
                ResponsesHTTPModel(name="m", endpoint=url, timeout_seconds=5).complete_with_receipt(
                    "原文", cancelled=cancelled.is_set)
            self.assertLess(time.monotonic() - started, 0.8)
            canceller.join(timeout=1)
        self.assertEqual(caught.exception.receipt["status"], "cancelled")
        self.assertEqual(len(calls), 1)

    def test_cancelled_before_dispatch_makes_no_request(self):
        with endpoint(respond({})) as (url, calls, _):
            with self.assertRaises(ModelProviderError) as caught:
                ResponsesHTTPModel(name="m", endpoint=url, timeout_seconds=3).complete_with_receipt("原文", cancelled=lambda: True)
        self.assertEqual(calls, [])
        self.assertEqual(caught.exception.receipt["status"], "cancelled")

    def test_response_byte_bound_is_enforced(self):
        with endpoint(respond({"status": "completed", "output_text": "文" * 50})) as (url, _, _):
            with self.assertRaisesRegex(ModelProviderError, "size limit"):
                ResponsesHTTPModel(name="m", endpoint=url, timeout_seconds=3, max_response_bytes=100).complete_with_receipt("原文")


if __name__ == "__main__":
    unittest.main()
