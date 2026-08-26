#!/usr/bin/env python3
"""Contract tests for the read-only validator READY enumerator."""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("validator_ready", ROOT / "tools" / "validator_ready.py")
assert SPEC and SPEC.loader
READY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = READY
SPEC.loader.exec_module(READY)
FIXTURE = ROOT / "tools" / "fixtures" / "validator-ready"


class ValidatorReadyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "validator"
        shutil.copytree(FIXTURE, self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def snapshot(self) -> dict:
        return READY.evaluate(READY.discover_records(self.root))

    def set_status(self, task: str, status: str) -> None:
        for path in self.root.glob("*.md"):
            text = path.read_text(encoding="utf-8")
            parsed = READY._split_front_matter(text)
            if parsed is None:
                continue
            front_matter, _ = parsed
            try:
                fields = READY._parse_front_matter(front_matter)
            except Exception:
                continue
            if READY._as_string(fields.get("task")) == task:
                path.write_text(
                    text.replace("status: planned", f"status: {status}", 1),
                    encoding="utf-8",
                )
                return
        self.fail(f"fixture task {task} not found")

    def test_two_sequential_leaves_and_parallel_branch(self) -> None:
        self.assertEqual([item["task"] for item in self.snapshot()["ready"]], ["VAL-A"])
        self.set_status("VAL-A", "completed")
        self.assertEqual(
            [item["task"] for item in self.snapshot()["ready"]],
            ["VAL-B", "VAL-C", "VAL-D"],
        )
        self.set_status("VAL-C", "completed")
        self.assertEqual(
            [item["task"] for item in self.snapshot()["ready"]],
            ["VAL-B", "VAL-D", "VAL-E"],
        )

    def test_finding_does_not_remove_unrelated_ready_leaves(self) -> None:
        self.set_status("VAL-A", "completed")
        target = self.root / "b.md"
        target.write_text(
            target.read_text(encoding="utf-8")
            + "\n## Validation Findings\n\nCV-TEST fail: observed fixture finding.\n",
            encoding="utf-8",
        )
        self.assertEqual(
            [item["task"] for item in self.snapshot()["ready"]],
            ["VAL-B", "VAL-C", "VAL-D"],
        )

    def test_architecture_blocker_and_tracker_reconciliation(self) -> None:
        snapshot = self.snapshot()
        blocked = next(item for item in snapshot["blocked"] if item["task"] == "VAL-BLOCKED")
        self.assertTrue(
            any("architecture-decision blocker" in reason for reason in blocked["reasons"])
        )
        self.assertEqual(
            {item["task"] for item in snapshot["reconciliation"]},
            {"TRACKER-1", "ROOT-248"},
        )
        for task in ("VAL-A", "VAL-B", "VAL-C", "VAL-D", "VAL-E", "VAL-BLOCKED"):
            self.set_status(task, "completed")
        snapshot = self.snapshot()
        eligible = {
            item["task"]
            for item in snapshot["reconciliation"]
            if item["eligible_for_reconciliation"]
        }
        self.assertEqual(eligible, {"TRACKER-1"})
        self.set_status("TRACKER-1", "completed")
        eligible = {
            item["task"]
            for item in self.snapshot()["reconciliation"]
            if item["eligible_for_reconciliation"]
        }
        self.assertEqual(eligible, {"TRACKER-1", "ROOT-248"})


if __name__ == "__main__":
    unittest.main()
