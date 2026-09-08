"""Bounded acceptance waits distinguish durable progress from live polling."""

from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ACCEPTANCE = Path(__file__).resolve().parents[1] / "acceptance"
if str(ACCEPTANCE) not in sys.path:
    sys.path.insert(0, str(ACCEPTANCE))
import _gate_support as S  # noqa: E402


class JobWaitTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.base = {
            "status": "running", "outputs": [], "chunks": [],
            "stages": [{"stage": "present", "status": "running"}],
        }

    def run_wait(self, snapshots, **kwargs):
        queue = iter(snapshots)
        last = snapshots[-1]

        def fetch(*args, **kwargs):
            return 200, {"job": copy.deepcopy(next(queue, last))}

        def sleep(seconds):
            self.now += seconds

        with mock.patch.object(S, "json_http", side_effect=fetch), mock.patch.object(
            S.time, "monotonic", side_effect=lambda: self.now
        ), mock.patch.object(S.time, "sleep", side_effect=sleep), redirect_stdout(io.StringIO()):
            return S.wait_job("http://unit.test", "auth", "job", wanted={"completed"}, **kwargs)

    def growing(self, count=5):
        snapshots = []
        for number in range(count):
            row = copy.deepcopy(self.base)
            row["outputs"] = [
                {"output_id": str(i), "artifact_type": "reader-presentation"}
                for i in range(number)
            ]
            snapshots.append(row)
        return snapshots

    def test_durable_presentations_allow_long_stage_and_are_journaled(self):
        snapshots = self.growing(4)
        snapshots[-1]["status"] = "completed"
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "progress.jsonl"
            result = self.run_wait(snapshots, timeout_seconds=10, idle_timeout_seconds=3, progress_path=journal)
            records = [json.loads(line) for line in journal.read_text().splitlines()]
        self.assertEqual("completed", result["status"])
        self.assertGreater(self.now, 3)
        self.assertEqual([0, 1, 2, 3], [r["reader_presentations"] for r in records])
        self.assertEqual("completed", records[-1]["status"])

    def test_heartbeats_and_repeated_outputs_do_not_renew_idle_deadline(self):
        snapshots = self.growing(2)[1:]
        for number in range(4):
            row = copy.deepcopy(snapshots[0])
            row.update(updated_at=str(number), lease_expires_at=str(number), attempt=number)
            snapshots.append(row)
        with self.assertRaisesRegex(S.GateError, "no durable progress"):
            self.run_wait(snapshots, timeout_seconds=20, idle_timeout_seconds=3)
        self.assertEqual(3, self.now)

    def test_continuous_progress_cannot_extend_absolute_limit(self):
        with self.assertRaisesRegex(S.GateError, "absolute wait limit"):
            self.run_wait(self.growing(8), timeout_seconds=6, idle_timeout_seconds=3)
        self.assertEqual(6, self.now)

    def test_unexpected_terminal_state_still_fails_immediately(self):
        for status in ("failed", "cancelled"):
            with self.subTest(status=status):
                failed = {**self.base, "status": status}
                with self.assertRaisesRegex(S.GateError, "unexpected terminal state"):
                    self.run_wait([failed], timeout_seconds=10, idle_timeout_seconds=3)
                self.assertEqual(0, self.now)

    def test_completed_checkpoints_renew_idle_time_without_completing_job(self):
        stage = copy.deepcopy(self.base)
        stage["stages"].insert(0, {"stage": "publish", "status": "completed"})
        chunk = copy.deepcopy(stage)
        chunk["chunks"] = [{"chunk_id": "1", "status": "completed"}]
        with self.assertRaisesRegex(S.GateError, "no durable progress"):
            self.run_wait([self.base, stage, chunk], timeout_seconds=20, idle_timeout_seconds=3)
        self.assertEqual(7, self.now)

    def test_simple_wait_keeps_absolute_timeout(self):
        with self.assertRaisesRegex(S.GateError, "absolute wait limit"):
            self.run_wait([self.base], timeout_seconds=3)
        self.assertEqual(3, self.now)

    def test_late_http_completion_cannot_bypass_absolute_limit(self):
        def fetch(*args, **kwargs):
            self.assertEqual(10, kwargs["timeout"])
            self.now = 11
            return 200, {"job": {**self.base, "status": "completed"}}

        with mock.patch.object(S, "json_http", side_effect=fetch), mock.patch.object(
            S.time, "monotonic", side_effect=lambda: self.now
        ):
            with self.assertRaisesRegex(S.GateError, "absolute wait limit"):
                S.wait_job("http://unit.test", "auth", "job", wanted={"completed"}, timeout_seconds=10)


if __name__ == "__main__":
    unittest.main()
