"""Dependency, recovery and bounded-attempt tests for the shared step runner."""
from __future__ import annotations

import sys
import threading
import time
import unittest
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
for path in (HERE, HERE.parent / "persistence"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from common import PersistenceError, sha256_json
from step_runner import (
    StepDefinition,
    StepInput,
    StepRunner,
    StepRunnerFailure,
    StepSpec,
)


class AttemptBudgetExhausted(PersistenceError):
    pass


class MemoryStepStore:
    """The same identity/attempt contract as chapter production storage."""

    def __init__(self, *, max_attempts=2):
        self.max_attempts = max_attempts
        self.plan = "p" * 64
        self.attempts = []
        self.outputs = []

    def begin_attempt(self, *, step, round, slot, data, prompt, model_config,
                      max_attempts, retryable, retry_prompt):
        key = StepInput(
            pipeline_fingerprint=self.plan,
            step=step,
            round=round,
            slot=slot,
            data=data,
            prompt=prompt,
            model_config=model_config,
        ).fingerprint()
        previous = [item for item in self.outputs if item["node_key"] == key]
        completed = [item for item in previous if item["status"] == "completed"]
        if completed:
            return completed[-1], True
        starts = [item for item in self.attempts if item["node_key"] == key]
        if len(starts) >= max_attempts:
            raise AttemptBudgetExhausted(f"{step}/{slot} budget exhausted")
        attempt = {
            "node_key": key,
            "step": step,
            "round": round,
            "slot": slot,
            "model": model_config["model"],
            "prompt": prompt,
            "attempt": len(starts) + 1,
            "output_sha256": sha256_json(["attempt", key, len(starts) + 1]),
            "status": "started",
        }
        self.attempts.append(attempt)
        return attempt, False

    def finish_attempt(self, *, attempt, raw_text, parsed, validation_errors,
                       receipt, status, error):
        output = {
            **attempt,
            "attempt_sha256": attempt["output_sha256"],
            "raw_text": raw_text,
            "parsed": parsed,
            "validation_errors": validation_errors,
            "receipt": receipt,
            "status": status,
            "error": error,
        }
        output["output_sha256"] = sha256_json(output)
        self.outputs.append(output)
        return output


class ScriptedModel:
    def __init__(self, script, step, *, gate=None):
        self.script = script
        self.step = step
        self.name = step
        self.gate = gate

    def complete(self, prompt):
        if self.gate is not None:
            self.gate(self.step)
        return self.script(self.step, prompt)


class SharedStepRunnerTests(unittest.TestCase):
    def runner(self, models, store, *, heartbeat=None, max_parallel=2):
        definitions = {
            "A": StepDefinition("A"),
            "B": StepDefinition("B"),
            "C": StepDefinition("C", dependencies=("A", "B")),
        }
        return StepRunner(
            definitions=definitions,
            model_slots=lambda step: (step,),
            model_for=lambda step, _slot: models[step],
            model_config=lambda step, _slot: {"model": step},
            build_prompt=lambda step, data: f"{step}:{data}",
            parse=lambda step, raw: ({"step": step, "raw": raw}, []),
            semantic_errors=lambda _step, _parsed, _data: [],
            begin_attempt=store.begin_attempt,
            finish_attempt=store.finish_attempt,
            retry_prompt=lambda prompt, _previous: prompt,
            heartbeat=heartbeat or (lambda: None),
            max_parallel=max_parallel,
            max_attempts=store.max_attempts,
            max_response_chars=1024,
            wait_timeout_seconds=0.01,
            preparation_exceptions=(AttemptBudgetExhausted,),
        )

    def test_independent_steps_run_in_parallel_and_dependency_waits(self):
        entered = {step: threading.Event() for step in "ABC"}
        release = threading.Event()

        def script(step, _prompt):
            entered[step].set()
            if step in "AB":
                self.assertTrue(release.wait(1), f"{step} was not released")
            else:
                self.assertTrue(entered["A"].is_set() and entered["B"].is_set())
            return step

        store = MemoryStepStore()
        models = {step: ScriptedModel(script, step) for step in "ABC"}
        runner = self.runner(models, store)
        result = {}

        def run():
            result.update(runner.execute([
                StepSpec("A", {"value": "a"}),
                StepSpec("B", {"value": "b"}),
                StepSpec("C", {"value": "c"}),
            ]))

        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(entered["A"].wait(1))
        self.assertTrue(entered["B"].wait(1))
        self.assertFalse(entered["C"].is_set(), "dependent C started before A/B were saved")
        release.set()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(set(result), {"A", "B", "C"})
        self.assertEqual(store.outputs[-1]["step"], "C")
        self.assertEqual({item["step"] for item in store.outputs[:-1]}, {"A", "B"})

    def test_resume_reuses_A_and_retries_only_failed_B_before_C(self):
        calls = defaultdict(int)

        def script(step, _prompt):
            calls[step] += 1
            if step == "B" and calls[step] == 1:
                raise RuntimeError("bounded provider failure")
            return step

        store = MemoryStepStore()
        models = {step: ScriptedModel(script, step) for step in "ABC"}
        runner = self.runner(models, store)
        specs = [
            StepSpec("A", {}),
            StepSpec("B", {}),
            StepSpec("C", {}),
        ]
        with self.assertRaises(StepRunnerFailure):
            runner.execute(specs)
        self.assertEqual(dict(calls), {"A": 1, "B": 1})
        self.assertFalse(any(item["step"] == "C" for item in store.attempts))

        runner.execute(specs)
        self.assertEqual(dict(calls), {"A": 1, "B": 2, "C": 1})
        self.assertEqual(
            [item["step"] for item in store.attempts], ["A", "B", "B", "C"]
        )

    def test_heartbeat_loss_cancels_active_model_before_result_is_saved(self):
        entered = threading.Event()
        stopped = threading.Event()

        def observed(_prompt, *, cancelled):
            entered.set()
            while not cancelled():
                time.sleep(0.005)
            stopped.set()
            raise RuntimeError("cancelled")

        def heartbeat():
            if entered.is_set():
                raise RuntimeError("lease lost")

        model = ScriptedModel(lambda _step, _prompt: "unreachable", "A")
        model.complete_with_receipt = observed
        store = MemoryStepStore()
        runner = self.runner({"A": model, "B": model, "C": model}, store, heartbeat=heartbeat)
        with self.assertRaisesRegex(RuntimeError, "lease lost"):
            runner.execute([StepSpec("A", {})])
        self.assertTrue(stopped.wait(1))
        self.assertEqual(store.outputs, [])

    def test_input_fingerprint_changes_when_prompt_or_profile_changes(self):
        base = StepInput("p" * 64, "A", 0, "slot", {"x": 1}, "prompt", {"model": "m"})
        self.assertNotEqual(base.fingerprint(), StepInput(
            "p" * 64, "A", 0, "slot", {"x": 1}, "changed", {"model": "m"}
        ).fingerprint())
        self.assertNotEqual(base.fingerprint(), StepInput(
            "p" * 64, "A", 0, "slot", {"x": 1}, "prompt", {"model": "other"}
        ).fingerprint())


if __name__ == "__main__":
    unittest.main()
