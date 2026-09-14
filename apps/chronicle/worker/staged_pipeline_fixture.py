"""Prompt-driven fixtures for the staged 0.4 chapter production contract.

The same fixture implementation serves the in-process worker tests and the
real-stack acceptance gate. It always receives the complete ``SOURCE``
envelope emitted by :mod:`chapter_production`, derives output from that
envelope, and leaves step parsing, candidate validation, durable runs, review,
and publication to the product pipeline. The old 0.1/0.2/0.3 fixture entry
points are intentionally not used here.
"""
from __future__ import annotations

import copy
import itertools
import json
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

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
    if not isinstance(source.get("normalized_text"), str) or not source["normalized_text"]:
        raise AssertionError("every model must receive the complete chapter")
    if not isinstance(source.get("source_scope"), dict):
        raise AssertionError("staged prompts must carry the program-owned source scope")
    return step, source, data


def _nth(text, quote, occurrence):
    start = -1
    for _ in range(occurrence):
        start = text.find(quote, start + 1)
        if start < 0:
            raise AssertionError("existing fixture quote is absent from its source")
    return start


def _request_from_source(source):
    """Reconstruct only the request fields required by the fixture builders.

    ``SOURCE`` is a prompt view, not a second request authority. The values
    below are copied from it and its program-generated source scope; the real
    request remains the value validated by ``staged_chapter_contract``.
    """
    scope = source["source_scope"]
    return {
        **copy.deepcopy(source),
        "revision_id": scope["revision_id"],
        "chapter_start": scope["chapter_start"],
        "chapter_end": scope["chapter_end"],
        "revision_normalized_sha256": scope["revision_normalized_sha256"],
        "schema_versions": {"candidate": "0.4", "bundle": "0.1"},
    }


def _program_scope(source):
    """Remove prompt-only fragment text before binding the candidate scope."""
    scope = copy.deepcopy(source["source_scope"])
    for fragment in scope.get("fragments", []):
        if isinstance(fragment, dict):
            fragment.pop("text", None)
    return scope


def _unique_mentions(text, count=2):
    """Choose short, verbatim, unique evidence snippets from a whole source."""
    result = []
    for length in (4, 6, 8, 10, 12):
        for start in range(0, max(0, len(text) - length + 1), max(1, length // 2)):
            snippet = text[start:start + length]
            if not snippet.strip() or "\n" in snippet or "#" in snippet:
                continue
            if snippet in result or text.count(snippet) != 1:
                continue
            result.append(snippet)
            if len(result) == count:
                return result
    if not result:
        compact = "".join(text.split())
        if compact:
            result.append(compact[: min(4, len(compact))])
    return result


def _generic_candidate_for_source(source):
    """Build a current 0.4 candidate for arbitrary natural chapters.

    The mature fixture builders already encode the frozen reading/person-state
    shapes and their source selectors. Reusing those pure builders here keeps
    this entry grounded while the staged wrapper adds the current source scope
    and version marker. No accepted artifact or program-owned hash is made by
    the fixture.
    """
    import fixture_model
    from reader_language import simplified

    request = _request_from_source(source)
    mentions = _unique_mentions(request["normalized_text"], 2)
    if not mentions:
        raise AssertionError("fixture source has no usable verbatim evidence")
    specs = [
        {"mention": mention, "type": "person", "name": mention}
        for mention in mentions
    ]
    spec = {
        "chapter_id": request["chapter_id"],
        "revision_id": request["revision_id"],
        "source_title": request.get("title") or "分阶段测试原文",
        # Production normalizes the complete translation to simplified Chinese
        # before linking. Keep the translated evidence in that coordinate
        # system while the source selectors below remain verbatim.
        "translation_text": f"fixture整章译文（{simplified(mentions[0])}）非真实内容验收文字",
        "entities": specs,
        "event": {"type": "appointment", "title": f"fixture事件（{mentions[0]}）"},
        "predicate": "affected",
    }
    candidate = fixture_model.build_person_state_chapter_candidate(request, spec)
    candidate["version"] = "0.4"
    candidate["source_scope"] = _program_scope(source)
    # The builder emits one complete translation block for all body blocks.
    # Keep every generated selector tied to the actual chapter request.
    _add_resolved_span(candidate, request)
    return candidate


def candidate_for_source(source):
    """Build a current 0.4 candidate, preserving the frozen sample regression."""
    if source["normalized_text"] != TEXT:
        return _generic_candidate_for_source(source)
    candidate = copy.deepcopy(ORIGINAL_CANDIDATE)
    candidate["chapter_id"] = source["chapter_id"]
    candidate["version"] = "0.4"
    candidate["source_scope"] = _program_scope(source)
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


def _add_resolved_span(candidate, request):
    """Add one translated event span without changing source anchors."""
    blocks = candidate.get("translation", {}).get("blocks", [])
    units = candidate.get("reading", {}).get("units", [])
    events = candidate.get("bundle", {}).get("events", [])
    mentions = candidate.get("mentions", [])
    if not blocks or not units or not events or not mentions:
        return
    event_ref = events[0]["temp_id"]
    mention = str(mentions[0].get("surface") or "")
    if not mention:
        return
    from reader_language import simplified

    translated_mention = simplified(mention)
    import fixture_model

    for unit in units:
        block = next(
            (item for item in blocks if item.get("block_id") == unit.get("block_id")),
            None,
        )
        if block is None or translated_mention not in block.get("text", ""):
            continue
        source_selection = fixture_model._chapter_selection_for(
            quote=mention,
            text=request["normalized_text"],
            blocks=request["blocks"],
            owner="staged gate reading span",
        )
        unit["event_spans"] = [{
            "span_id": "es_001",
            "selection": {"quote": translated_mention, "occurrence": 1},
            "status": "resolved",
            "target_ref": event_ref,
            "candidate_refs": [],
            "relation": "current",
            "source_selections": [source_selection],
        }]
        unit["current_event_refs"] = [event_ref]
        return


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
            prose = [block["text"] for block in candidate["translation"]["blocks"]]
            if source["normalized_text"] == TEXT and self.mode in ("revise", "human_revision"):
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
            replacement = CORRECT_FIRST
            if source["normalized_text"] != TEXT:
                replacement = data["candidate"]["translation"]["blocks"][0]["text"]
            result = {"candidate_sha256": data["candidate_sha256"], "history_sha256": data["history_sha256"],
                      "addressed_issue_ids": [issue["id"] for issue in data["issues"]],
                      "rationale": "按原文恢复任命者孙策与受任者周瑜。",
                      "patches": [{"op": "replace", "path": path,
                                   "before_sha256": data["patch_targets"][path], "value": replacement}]}
        elif step == "comparison":
            candidates = data.get("candidates") or []
            if not candidates:
                raise AssertionError("comparison must receive a fixed candidate set")
            selected = candidates[0]["candidate_sha256"]
            result = {
                "candidate_set_sha256": data["candidate_set_sha256"],
                "selected_sha256": selected,
                "differences": [
                    {
                        "candidate_sha256": item["candidate_sha256"],
                        "assessment": "selected" if index == 0 else "compatible",
                        "rationale": "fixture comparison keeps the first complete output; no new content is generated.",
                        "evidence": [
                            fragment["id"] for fragment in source["source_scope"]["fragments"]
                            if fragment["role"] == "body"
                        ][:1],
                    }
                    for index, item in enumerate(candidates)
                ],
            }
        else:
            raise AssertionError("unknown staged fixture step")
        return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# The same fixture boundary serves the explicit history synthesis stage.
# ---------------------------------------------------------------------------


def narrative_drafts(context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build deterministic facts/prose over the context supplied by the worker."""
    sources = context.get("sources")
    if not isinstance(sources, list) or not sources:
        raise AssertionError("narrative fixture requires published sources")
    phases, facts, paragraphs = [], [], []
    for index, source in enumerate(sources):
        phase, fact = f"p{index}", f"f{index}"
        translation = source.get("translation") or []
        text = "\n".join(str(block.get("text") or "") for block in translation)
        if len(text) < 600:
            text += "\n" + (
                "合成排版验收文字：用于检查连续滚动、阅读位置和人物阶段同步，"
                "不包含史实补充，不能作为真实译文或历史内容验收证据。"
            ) * 12
        canonical = source.get("canonical_refs") or {}
        entity = next(iter((canonical.get("entities") or {}).values()), None)
        event = next(iter((canonical.get("events") or {}).values()), None)
        evidence = (source.get("evidence") or [{}])[0]
        evidence_id = evidence.get("id")
        if not evidence_id:
            raise AssertionError("narrative source has no evidence handle")
        phases.append({
            "id": phase, "label": source.get("title") or f"source-{index}",
            "year": None, "period": None, "basis": [evidence_id],
            "relation_to_previous": "uncertain",
        })
        facts.append({
            "id": fact, "question": "这一来源如何描述人物？", "subject_id": entity,
            "event_id": event, "dimension": "event_detail", "phase_ids": [phase],
            "text": evidence.get("quote") or "原文记录", "value": None,
            "certainty": "clear", "reason": "限于这份来源明确记载的范围。",
            "evidence": [{"id": evidence_id, "relation": "support", "attribution": "本传作者", "note": "原文明载。"}],
        })
        paragraphs.append({
            "id": f"n{index}", "phase_id": phase,
            "segments": [{
                "text": text, "conclusion_ids": [fact], "event_id": event,
                "event_relation": "current" if event else None, "event_text": None,
            }],
            "entities": [{"entity_id": entity, "importance": "primary"}] if entity else [],
        })
    relations = [
        {"left": left["source_id"], "right": right["source_id"], "relation": "unknown",
         "reason": "此测试不对史料独立性作断言。"}
        for left, right in itertools.combinations(sources, 2)
    ]
    entries = [{
        "label": "合成历史进程", "kind": "period", "paragraph_id": "n0",
        "event_id": None, "reason": "概览这一组已核对资料的完整历史发展。",
    }]
    return (
        {
            "schema": "chronicle.source-corroboration", "version": "0.1",
            "title": "分阶段 fixture 综合叙事（非真实内容）", "phases": phases,
            "conclusions": facts, "source_relations": relations,
        },
        {
            "schema": "chronicle.historical-narrative", "version": "0.1",
            "paragraphs": paragraphs,
            "navigation": [{
                "label": "测试时段", "first_paragraph_id": paragraphs[0]["id"],
                "last_paragraph_id": paragraphs[-1]["id"],
                "items": [{key: entry[key] for key in ("paragraph_id", "label", "reason")} for entry in entries],
            }],
            "entry_points": entries,
        },
    )


def add_reviewed_person_states(context: dict[str, Any], facts: dict[str, Any], prose: dict[str, Any]) -> None:
    """Bind reviewed source states to their source phase in synthesis."""
    for index, source in enumerate(context.get("sources") or []):
        for state in source.get("reviewed_person_states") or []:
            person_id = state.get("person_id")
            value = state.get("value") or state.get("target")
            if not person_id or not value:
                continue
            conclusion_id = f"s{index}"
            if any(item.get("id") == conclusion_id for item in facts["conclusions"]):
                continue
            evidence_id = source["evidence"][0]["id"]
            facts["conclusions"].append({
                "id": conclusion_id, "question": "该人物在此阶段的身份",
                "subject_id": person_id, "event_id": None, "dimension": "office",
                "phase_ids": [f"p{index}"],
                "text": "据已审核来源阶段资料，该人物在此阶段有此身份。",
                "value": str(value), "certainty": state.get("certainty", "uncertain"),
                "reason": "据已审核来源阶段资料。",
                "evidence": [{"id": evidence_id, "relation": "support", "attribution": "本传作者", "note": "已审核来源阶段资料。"}],
            })
            prose["paragraphs"][index]["segments"][0]["conclusion_ids"].append(conclusion_id)


def _narrative_context(prompt: str) -> dict[str, Any]:
    marker = "\nINPUT="
    at = prompt.find(marker)
    if at < 0:
        raise AssertionError("narrative prompt is missing INPUT")
    context = json.loads(prompt[at + len(marker):].split("\n", 1)[0])
    if not isinstance(context, dict) or not context.get("sources"):
        raise AssertionError("narrative prompt carries no sources")
    return context


def narrative_candidate(prompt: str) -> str:
    marker = "\nSTAGE="
    if marker not in prompt:
        raise AssertionError("narrative prompt is missing STAGE")
    stage = prompt.split(marker, 1)[1].split("\n", 1)[0]
    if stage not in ("facts", "prose"):
        raise AssertionError(f"unknown narrative stage {stage!r}")
    context = _narrative_context(prompt)
    facts, prose = narrative_drafts(context)
    add_reviewed_person_states(context, facts, prose)
    return json.dumps(facts if stage == "facts" else prose, ensure_ascii=False)


class StagedFixtureProvider:
    """HTTP Responses-protocol fixture used by the current acceptance gate."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.fail_token: str | None = None
        self.calls: list[str] = []

    def _handler(self):
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                try:
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                    prompt = str(body.get("input", ""))
                    if provider.fail_token and provider.fail_token in prompt:
                        output = "{\"broken\":true}"
                    elif "CHRONICLE_STEP=" in prompt:
                        step, _source, _data = parse_prompt(prompt)
                        # Run the same step fixture as the in-process tests;
                        # transport is the only boundary changed by this class.
                        script = ScriptedModels()
                        output = script.complete(step, "executor", prompt)
                        provider.calls.append(f"chapter:{step}")
                    else:
                        output = narrative_candidate(prompt)
                        provider.calls.append("narrative")
                    payload = {
                        "status": "completed",
                        "output": [{"type": "message", "content": [{"type": "output_text", "text": output}]}],
                    }
                    self._respond(200, payload)
                except Exception as exc:  # noqa: BLE001 - endpoint must fail closed
                    self._respond(500, {"status": "failed", "error": {"message": str(exc)[:500]}})

            def _respond(self, status: int, payload: dict[str, Any]) -> None:
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        return Handler

    def start(self) -> None:
        self.server = ThreadingHTTPServer(("0.0.0.0", self.port), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)
