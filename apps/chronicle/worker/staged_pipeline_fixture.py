"""Prompt-driven, in-process model fixture for staged worker integration tests.

The evidence graph is the existing C2-R3 contract sample, rebound to the
SOURCE envelope actually emitted by build_prompt. No fixture bypasses the
step parser, candidate validator, durable Runner, or chapter acceptance.
"""
from __future__ import annotations

import copy
import json
import threading
from collections import Counter
from pathlib import Path

import chapter_production as protocol
from chapter_models import ChapterModels
from model_provider import DEFAULT_MODEL_TIMEOUT_SECONDS, ModelProviderError

FIXTURES = Path(__file__).resolve().parent.parent / "ingestion" / "fixtures" / "c2r3-contract"
ORIGINAL_REQUEST = json.loads((FIXTURES / "request.json").read_text(encoding="utf-8"))
ORIGINAL_CANDIDATE = json.loads((FIXTURES / "candidate-valid.json").read_text(encoding="utf-8"))
TEXT = ORIGINAL_REQUEST["normalized_text"] + "\n\n〈裴松之注：另說不確，仍存。〉"
CORRECT_FIRST = "建安三年，孙策授予周瑜建威中郎将。"
WRONG_FIRST = "建安三年，周瑜授予孙策建威中郎将。"
PROSE = [CORRECT_FIRST, "周瑜担任前部大督，后来拜为偏将军，兼任南郡太守。", "孙权派周瑜返回。"]


def parse_prompt(prompt):
    lines = prompt.splitlines()
    step = lines[0].removeprefix("CHRONICLE_STEP=")
    if step not in protocol.STEPS:
        raise AssertionError("fixture must receive an actual staged prompt")
    source = json.loads(next(line[7:] for line in lines if line.startswith("SOURCE=")))
    data = json.loads(next(line[5:] for line in lines if line.startswith("DATA=")))
    if source["normalized_text"] != TEXT:
        raise AssertionError("every model must receive the complete chapter, including its annotation")
    return step, source, data


def _nth(text, quote, occurrence):
    start = -1
    for _ in range(occurrence):
        start = text.find(quote, start + 1)
        if start < 0:
            raise AssertionError("existing fixture quote is absent from its source")
    return start


def candidate_for_source(source):
    """Map the old sample's exact quote locations to actual planned blocks."""
    candidate = copy.deepcopy(ORIGINAL_CANDIDATE)
    candidate["chapter_id"] = source["chapter_id"]
    candidate["version"] = "0.4"
    candidate["source_scope"] = copy.deepcopy(source["source_scope"])
    candidate["bundle"]["source"]["title"] = source["title"] or "分阶段测试原文"
    old_blocks = {block["block_id"]: block for block in ORIGINAL_REQUEST["blocks"]}
    actual_blocks = source["blocks"]
    text = source["normalized_text"]
    source_offset = text.index(ORIGINAL_REQUEST["normalized_text"])

    def map_selection(selection):
        old_first = old_blocks[selection["first_block_id"]]
        old_last = old_blocks[selection["last_block_id"]]
        old_window = ORIGINAL_REQUEST["normalized_text"][old_first["start"]:old_last["end"]]
        start = source_offset + old_first["start"] + _nth(old_window, selection["quote"], selection["occurrence"])
        end = start + len(selection["quote"])
        first = next(block for block in actual_blocks if block["start"] <= start < block["end"])
        last = next(block for block in actual_blocks if block["start"] < end <= block["end"])
        window = text[first["start"]:last["end"]]
        relative = start - first["start"]
        occurrence, found = 0, -1
        while found < relative:
            found = window.find(selection["quote"], found + 1)
            if found < 0:
                raise AssertionError("rebound source quote is absent")
            occurrence += 1
        if found != relative:
            raise AssertionError("fixture rebound a quote to another occurrence")
        selection.update(first_block_id=first["block_id"], last_block_id=last["block_id"], occurrence=occurrence)

    def visit(value):
        if isinstance(value, dict):
            if {"first_block_id", "last_block_id", "quote", "occurrence"} <= set(value):
                map_selection(value)
            else:
                for child in value.values():
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(candidate)
    for index, block in enumerate(candidate["translation"]["blocks"]):
        old = old_blocks[block["source_block_ids"][0]]
        block["source_block_ids"] = [entry["block_id"] for entry in actual_blocks
            if entry["start"] < source_offset + old["end"]
            and entry["end"] > source_offset + old["start"]]
        block["block_id"] = f"tr_{index + 1:03d}"
        block["text"] = PROSE[index]
        candidate["reading"]["units"][index]["block_id"] = block["block_id"]
        candidate["person_states"]["unit_phases"][index]["block_id"] = block["block_id"]
    return candidate


class _StepModel:
    def __init__(self, script, step, slot):
        self.script, self.step, self.slot = script, step, slot
        self.name = "staged-fixture-" + slot

    def complete(self, prompt):
        return self.script.complete(self.step, self.slot, prompt)


class ScriptedModels:
    """Actual per-step model config plus bounded transport fault injection."""
    def __init__(self, *, mode="pass", failures=None, reviewers=1, parallel_barrier=False):
        self.mode, self.failures = mode, failures or {}
        self.calls = Counter()
        self.inputs = []
        self._lock = threading.Lock()
        self._barrier = threading.Barrier(2) if parallel_barrier else None
        self.deny_calls = False
        review_slots = tuple(f"reviewer_{index}" for index in range(reviewers))
        profiles = {slot: {
            "model": "staged-fixture-" + slot, "endpoint": "http://fixture.invalid/v1/responses",
            "api_key_env": "CHRONICLE_TEST_UNUSED_KEY", "timeout_seconds": DEFAULT_MODEL_TIMEOUT_SECONDS,
            "max_output_tokens": 65536,
            "max_response_bytes": 4194304, "response_format": "json_object",
        } for slot in ("executor", *review_slots)}
        steps = {step: review_slots if step == "review" else ("executor",)
                 for step in protocol.STEPS}
        providers = {(step, slot): _StepModel(self, step, slot)
                     for step, slots in steps.items() for slot in slots}
        self.models = ChapterModels(
            name="staged-fixture", profiles=profiles, steps=steps, providers=providers,
            max_parallel=2, max_step_attempts=2, max_repair_rounds=1,
        )

    def count(self, step, slot=None):
        return sum(count for (kind, profile), count in self.calls.items()
                   if kind == step and (slot is None or slot == profile))

    def complete(self, expected_step, slot, prompt):
        step, source, data = parse_prompt(prompt)
        if step != expected_step:
            raise AssertionError("provider slot received another step's prompt")
        with self._lock:
            self.calls[(step, slot)] += 1
            attempt = self.calls[(step, slot)]
            self.inputs.append({"step": step, "slot": slot, "attempt": attempt,
                                "source": copy.deepcopy(source), "data": copy.deepcopy(data)})
        if self.deny_calls:
            raise AssertionError("completed outputs must be adopted without another model call")
        if self._barrier is not None and step in ("translation", "extraction") and attempt == 1:
            self._barrier.wait(timeout=10)
        if attempt in self.failures.get((step, slot), set()):
            raise ModelProviderError("injected bounded transport failure", raw_text="{\"partial\":",
                                     receipt={"status": "failed", "usage": None, "http_attempts": 1})
        candidate = candidate_for_source(source)
        if step == "translation":
            if data:
                raise AssertionError("translation must not depend on the extraction result")
            prose = list(PROSE)
            if self.mode in ("revise", "human_revision"):
                prose[0] = WRONG_FIRST
            return "\n\n".join(prose)
        if step == "extraction":
            if data:
                raise AssertionError("extraction must be independent of translation")
            result = {key: candidate[key] for key in
                      ("chapter_id", "bundle", "mentions", "record_sources", "person_states", "warnings")}
            result["person_states"].pop("unit_phases")
        elif step == "linking":
            blocks = data["translation"]["blocks"]
            if len(blocks) != len(candidate["translation"]["blocks"]):
                raise AssertionError("saved translation lost a paragraph")
            result = {"chapter_id": source["chapter_id"],
                "translation_links": [{key: value for key, value in block.items() if key != "text"}
                                      for block in candidate["translation"]["blocks"]],
                "reading": candidate["reading"], "unit_phases": candidate["person_states"]["unit_phases"]}
            for index, block in enumerate(blocks):
                result["translation_links"][index]["block_id"] = block["block_id"]
                result["reading"]["units"][index]["block_id"] = block["block_id"]
                result["unit_phases"][index]["block_id"] = block["block_id"]
        elif step == "review":
            body = [fragment["id"] for fragment in source["source_scope"]["fragments"]
                    if fragment["role"] == "body"]
            wrong = data["candidate"]["translation"]["blocks"][0]["text"] == WRONG_FIRST
            verdict = "needs_review" if self.mode == "gate" or (wrong and self.mode == "human_revision") else "revise" if wrong else "pass"
            issues = [{"id": "subject-assignment", "type": "processing_error",
                       "target": "/translation/blocks/0/text",
                       "message": "需核对任命者与受任者，不能交换孙策与周瑜。", "evidence": body[:1],
                       "represented": False}] if verdict != "pass" else []
            result = {"candidate_sha256": data["candidate_sha256"], "history_sha256": data["history_sha256"],
                      "verdict": verdict, "coverage": body, "issues": issues,
                      "dispositions": [{"issue_id": issue["id"],
                          "disposition": "unresolved" if wrong else "resolved",
                          "rationale": "原文明确为策授瑜，已逐项核对当前版本。", "evidence": body[:1]}
                          for issue in data["previous_issues"]]}
        elif step == "repair":
            path = "/translation/blocks/0/text"
            result = {"candidate_sha256": data["candidate_sha256"], "history_sha256": data["history_sha256"],
                      "addressed_issue_ids": [issue["id"] for issue in data["issues"]],
                      "rationale": "按原文恢复任命者孙策与受任者周瑜。",
                      "patches": [{"op": "replace", "path": path,
                                   "before_sha256": data["patch_targets"][path], "value": CORRECT_FIRST}]}
        else:
            raise AssertionError("single generation candidates must not invoke comparison")
        return json.dumps(result, ensure_ascii=False)
