"""Stop semantics at the bounded scheduler/provider boundary."""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
for path in (HERE, HERE.parent / "persistence"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import staged_chapter as staged
from model_provider import ModelProviderError


class StagedSchedulerTests(unittest.TestCase):
    def runner(self, providers, heartbeat):
        runner = staged.Runner.__new__(staged.Runner)
        runner.database_url = "unused"
        runner.job_id = runner.chunk_id = "test"
        runner.worker = "worker"
        runner.request = {"chapter_id": "chapter"}
        runner.plan = {}
        runner.lease_seconds = 0.3
        runner.on_event = None
        runner.limits = SimpleNamespace(max_prompt_chars=100000, max_response_chars=10000)
        runner.models = SimpleNamespace(
            steps={"translation": tuple(providers)}, max_parallel=1, max_step_attempts=2,
            model_for=lambda step, slot: providers[slot],
            config_for=lambda step, slot: {"model": slot},
        )
        runner._heartbeat = heartbeat
        return runner

    def attempt(self, *args, **kwargs):
        return {"step": kwargs["step"], "slot": kwargs["slot"], "model": kwargs["slot"],
                "prompt": kwargs["prompt"], "round": kwargs["round"],
                "attempt": 1, "output_sha256": kwargs["slot"], "status": "started"}, False

    def test_stop_does_not_dispatch_or_reserve_queued_models(self):
        invoked = []
        def complete(slot):
            invoked.append(slot)
            return "完整译文"
        providers = {slot: SimpleNamespace(name=slot, complete=lambda prompt, slot=slot: complete(slot)) for slot in "ABCD"}
        def heartbeat():
            if invoked:
                raise staged.PipelineHalted("cancelled")
        runner = self.runner(providers, heartbeat)
        with patch.object(staged.psycopg, "connect"), patch.object(staged.store, "begin_attempt", side_effect=self.attempt) as begin, \
                patch.object(staged.store, "finish_attempt") as finish:
            with self.assertRaises(staged.PipelineHalted):
                runner._execute([("translation", {}, 0)])
        self.assertEqual(invoked, ["A"])
        self.assertEqual(begin.call_count, 1)
        finish.assert_not_called()

    def test_lost_lease_signals_active_transport_without_waiting_for_deadline(self):
        entered = threading.Event()
        stopped = threading.Event()
        def observed(prompt, *, cancelled):
            entered.set()
            until = time.monotonic() + 3
            while time.monotonic() < until:
                if cancelled():
                    stopped.set()
                    raise ModelProviderError("cancelled")
                time.sleep(0.005)
            return "迟到结果", {"status": "completed"}
        def heartbeat():
            if entered.is_set():
                raise staged.LeaseLost("lease expired")
        runner = self.runner({"A": SimpleNamespace(name="A", complete_with_receipt=observed)}, heartbeat)
        with patch.object(staged.psycopg, "connect"), patch.object(staged.store, "begin_attempt", side_effect=self.attempt), \
                patch.object(staged.store, "finish_attempt") as finish:
            start = time.monotonic()
            with self.assertRaises(staged.LeaseLost):
                runner._execute([("translation", {}, 0)])
            self.assertLess(time.monotonic() - start, 1)
            self.assertTrue(stopped.wait(1))
        finish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
