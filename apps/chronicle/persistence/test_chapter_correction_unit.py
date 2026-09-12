"""Offline regression of whole-chapter corrections, including the live v4 failure.

Scripted model responses exercise generation AND history without paid calls.
Passing these tests proves repair boundaries, not historical content accuracy.
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import chapter_extraction as X  # noqa: E402
import reading_contract as R  # noqa: E402


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def base(version: str) -> tuple[dict, dict]:
    directory = HERE.parent / "ingestion" / "fixtures" / f"c2r{version[-1]}-contract"
    return load(directory / "request.json"), load(directory / "candidate-valid.json")


class ScriptedModel:
    name = "offline-correction-regression"

    def __init__(self, *candidates: dict | str) -> None:
        self.responses = [
            value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            for value in candidates
        ]
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.responses[len(self.prompts) - 1]


def bad_anchor(candidate: dict) -> dict:
    candidate = copy.deepcopy(candidate)
    candidate["record_sources"][0]["selections"][0]["occurrence"] = 99
    return candidate


class TranslationCorrectionTests(unittest.TestCase):
    def test_metadata_repairs_preserve_prose_but_can_change_refs(self) -> None:
        for version in ("0.2", "0.3"):
            with self.subTest(version=version):
                request, valid = base(version)
                initial = bad_anchor(valid)
                block = initial["translation"]["blocks"][0]
                block["source_block_ids"].append("b_002")
                block["entity_refs"].append({"kind": "entity", "ref": "ent_999"})
                block["event_refs"].append({"kind": "event", "ref": "evt_999"})
                model = ScriptedModel(initial, valid)
                result = X.extract_chapter(request, model)
                self.assertTrue(result["accepted"], result["error"])
                check = result["attempts"][1]["correction_validation"]
                self.assertEqual(check["mode"], "preserve_translation")
                self.assertTrue(check["passed"])
                self.assertEqual(result["artifact"]["candidate"], valid)
                self.assertEqual(X.verify_history(result, request=request), [])
                prompt = model.prompts[1]
                self.assertIn(request["normalized_text"], prompt)
                self.assertGreater(prompt.index("CORRECTION RE-ASK"), prompt.index("---END CHAPTER---"))
                self.assertIn("METADATA CORRECTION ONLY", prompt)
                self.assertNotIn("expand any omitted", prompt)
                self.assertNotIn("TRANSLATION IS ALREADY CORRECT", prompt)

    def test_span_can_move_to_its_actual_block_without_rewriting_prose(self) -> None:
        request, valid = base("0.2")
        initial = copy.deepcopy(valid)
        initial["reading"]["units"][0]["event_spans"].append(
            initial["reading"]["units"][1]["event_spans"].pop()
        )
        result = X.extract_chapter(request, ScriptedModel(initial, valid))
        self.assertTrue(result["accepted"], result["error"])
        self.assertEqual(result["attempts"][1]["correction_validation"]["mode"], "preserve_translation")
        self.assertEqual(X.verify_history(result, request=request), [])

    def test_text_rewrites_and_expansions_are_rejected_during_metadata_repair(self) -> None:
        for version in ("0.2", "0.3"):
            request, valid = base(version)
            for replacement in ("这是一段概述。", valid["translation"]["blocks"][0]["text"] + "补充叙事。"):
                with self.subTest(version=version, text=replacement):
                    corrected = copy.deepcopy(valid)
                    corrected["translation"]["blocks"][0]["text"] = replacement
                    result = X.extract_chapter(request, ScriptedModel(bad_anchor(valid), corrected))
                    # The candidate's shape passes: only the cross-draft check
                    # prevents publishing a changed/condensed translation.
                    self.assertTrue(result["attempts"][1]["validation"]["passed"])
                    self.assertFalse(result["accepted"])
                    self.assertIsNone(result["artifact"])
                    self.assertIn("translation_preservation", result["error"]["categories"])
                    self.assertEqual(result["attempts"][1]["candidate"], corrected)
                    self.assertEqual(X.verify_history(result, request=request), [])

    def test_collapsing_all_blocks_cannot_pass_by_claiming_full_source_coverage(self) -> None:
        request, valid = base("0.2")
        corrected = copy.deepcopy(valid)
        first = corrected["translation"]["blocks"][0]
        first["source_block_ids"] = list(request["required_block_ids"])
        corrected["translation"]["blocks"] = [first]
        corrected["reading"]["units"] = corrected["reading"]["units"][:1]
        result = X.extract_chapter(request, ScriptedModel(bad_anchor(valid), corrected))
        self.assertTrue(result["attempts"][1]["validation"]["passed"])
        self.assertFalse(result["accepted"])
        self.assertIn("translation_preservation", result["error"]["categories"])
        self.assertEqual(result["correction_rounds_used"], 1)
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(X.verify_history(result, request=request), [])

    def test_block_renumbering_is_not_a_metadata_repair(self) -> None:
        for version in ("0.2", "0.3"):
            with self.subTest(version=version):
                request, valid = base(version)
                corrected = json.loads(json.dumps(valid).replace('"t_001"', '"t_999"'))
                result = X.extract_chapter(request, ScriptedModel(bad_anchor(valid), corrected))
                self.assertTrue(result["attempts"][1]["validation"]["passed"])
                self.assertFalse(result["accepted"])
                self.assertEqual(X.verify_history(result, request=request), [])

    def test_structural_failures_keep_whole_chapter_repair_available(self) -> None:
        for version in ("0.2", "0.3"):
            request, valid = base(version)
            for defect in ("missing_tail", "empty_text", "duplicate_id", "invalid_id", "overlong"):
                with self.subTest(version=version, defect=defect):
                    initial = copy.deepcopy(valid)
                    blocks = initial["translation"]["blocks"]
                    if defect == "missing_tail":
                        blocks.pop()
                        initial["reading"]["units"].pop()
                        if version == "0.3":
                            initial["person_states"]["unit_phases"].pop()
                    elif defect == "empty_text":
                        blocks[0]["text"] = ""
                    elif defect == "duplicate_id":
                        blocks[1]["block_id"] = blocks[0]["block_id"]
                    elif defect == "invalid_id":
                        blocks[0]["block_id"] = ""
                    else:
                        blocks[0]["text"] += "长" * R.ReadingLimits().max_block_code_points
                    model = ScriptedModel(initial, valid)
                    result = X.extract_chapter(request, model)
                    self.assertTrue(result["accepted"], result["error"])
                    self.assertEqual(result["attempts"][1]["correction_validation"]["mode"], "whole_chapter")
                    self.assertNotIn("METADATA CORRECTION ONLY", model.prompts[1])
                    self.assertEqual(X.verify_history(result, request=request), [])

    def test_parse_failure_has_no_prose_to_preserve(self) -> None:
        for version in ("0.2", "0.3"):
            with self.subTest(version=version):
                request, valid = base(version)
                result = X.extract_chapter(request, ScriptedModel("not JSON", valid))
                self.assertTrue(result["accepted"], result["error"])
                self.assertEqual(result["attempts"][1]["correction_validation"]["mode"], "whole_chapter")
                self.assertEqual(X.verify_history(result, request=request), [])

    def test_unknown_errors_cannot_be_hidden_by_diagnostic_truncation(self) -> None:
        request, valid = base("0.2")
        initial = bad_anchor(valid)
        report = R.validate_reading_annotations(request, initial)
        report["errors"]["future_prose_check"] = ["a newly detected translation defect"]
        # The policy sees the original report, including an unknown category
        # after more than the model prompt's twenty-error diagnostic budget.
        report["errors"]["chapter"] *= 25
        self.assertFalse(X._preserve_translation(initial, report, candidate_version="0.2"))

    def test_live_v4_collapse_records_prose_loss_and_replays_without_network(self) -> None:
        evidence = load(HERE.parent / "corpus" / "second-round" / "acceptance" / "candidate-live-r2-20260912-v4.json")
        request = evidence["request"]
        initial, corrected = [attempt["candidate"] for attempt in evidence["attempts"]]
        model = ScriptedModel(initial, corrected)
        result = X.extract_chapter(request, model)
        self.assertFalse(result["accepted"])
        self.assertEqual(len(model.prompts), 2)
        correction = result["attempts"][1]["correction_validation"]
        self.assertEqual(correction["mode"], "preserve_translation")
        self.assertFalse(correction["passed"])
        for block_id in ("t_016", "t_020", "t_021"):
            self.assertTrue(any(block_id in error for error in correction["errors"]), block_id)
        for saved, replayed in zip(evidence["attempts"], result["attempts"]):
            self.assertEqual(saved["candidate"], replayed["candidate"])
            self.assertEqual(saved["validation"], replayed["validation"])
        self.assertEqual(X.verify_history(result, request=request), [])


class CorrectionHistoryTests(unittest.TestCase):
    def rejected_rewrite(self, version: str) -> tuple[dict, dict]:
        request, valid = base(version)
        corrected = copy.deepcopy(valid)
        corrected["translation"]["blocks"][0]["text"] += "改写。"
        result = X.extract_chapter(request, ScriptedModel(bad_anchor(valid), corrected))
        self.assertFalse(result["accepted"])
        self.assertTrue(result["attempts"][1]["validation"]["passed"])
        return request, result

    def test_replay_detects_tampered_missing_or_bypassed_correction_result(self) -> None:
        for version in ("0.2", "0.3"):
            request, result = self.rejected_rewrite(version)
            for tamper in ("passed", "mode", "missing_check", "accepted", "initial_raw", "kind"):
                with self.subTest(version=version, tamper=tamper):
                    changed = copy.deepcopy(result)
                    attempt = changed["attempts"][1]
                    if tamper == "passed":
                        attempt["correction_validation"]["passed"] = True
                    elif tamper == "mode":
                        attempt["correction_validation"]["mode"] = "whole_chapter"
                    elif tamper == "missing_check":
                        attempt.pop("correction_validation")
                    elif tamper == "accepted":
                        changed["accepted"] = True
                    elif tamper == "initial_raw":
                        changed["attempts"][0]["raw_response"] = attempt["raw_response"]
                    else:
                        attempt["kind"] = "initial"
                    self.assertTrue(X.verify_history(changed, request=request))

    def test_unknown_or_missing_policy_versions_fail_replay(self) -> None:
        request, result = self.rejected_rewrite("0.3")
        for key in ("extraction_version", "correction_policy_version", "prompt_version"):
            for value in (None, "future-policy"):
                with self.subTest(key=key, value=value):
                    changed = copy.deepcopy(result)
                    changed["fingerprints"][key] = value
                    self.assertTrue(X.verify_history(changed, request=request))
        for malformed in (None, [], ["malformed"]):
            changed = copy.deepcopy(result)
            changed["fingerprints"] = malformed
            self.assertTrue(X.verify_history(changed, request=request))

    def test_new_runs_cannot_be_relabelled_as_legacy(self) -> None:
        for version, legacy_prompt in (("0.2", "c2r2-chapter-prompt-v4"), ("0.3", "c2r3-chapter-prompt-v2")):
            request, result = self.rejected_rewrite(version)
            result["fingerprints"]["extraction_version"] = f"c2r{version[-1]}-extraction-v1"
            result["fingerprints"].pop("correction_policy_version")
            result["attempts"][1].pop("correction_validation")
            result["accepted"] = True
            self.assertTrue(X.verify_history(result, request=request))
            # Relabelling the run-level prompt must still disagree with the
            # actual prompt header; editing that header breaks its saved hash.
            current_prompt = result["fingerprints"]["prompt_version"]
            result["fingerprints"]["prompt_version"] = legacy_prompt
            self.assertTrue(X.verify_history(result, request=request))
            for attempt in result["attempts"]:
                attempt["prompt"] = attempt["prompt"].replace(current_prompt, legacy_prompt)
            self.assertTrue(X.verify_history(result, request=request))

    def test_initial_prose_cannot_change_while_retaining_the_same_validator_errors(self) -> None:
        request, result = self.rejected_rewrite("0.2")
        initial, correction = result["attempts"]
        changed_candidate = json.loads(initial["raw_response"])
        changed_candidate["translation"]["blocks"][0]["text"] = correction["candidate"]["translation"]["blocks"][0]["text"]
        initial["raw_response"] = json.dumps(changed_candidate, ensure_ascii=False)
        correction["correction_validation"].update(passed=True, errors=[])
        result["accepted"] = True
        self.assertTrue(X.verify_history(result, request=request))
        initial.update(
            raw_response_sha256=X.sha256_text(initial["raw_response"]),
            raw_response_chars=len(initial["raw_response"]),
            raw_response_bytes=len(initial["raw_response"].encode("utf-8")),
        )
        self.assertTrue(X.verify_history(result, request=request))  # Cached candidate still disagrees.

    def test_missing_initial_evidence_cannot_disable_preservation(self) -> None:
        for version in ("0.2", "0.3"):
            for missing in ("raw_response", "validation", "both"):
                with self.subTest(version=version, missing=missing):
                    request, result = self.rejected_rewrite(version)
                    initial = result["attempts"][0]
                    for key in (("raw_response", "validation") if missing == "both" else (missing,)):
                        initial.pop(key)
                    result["attempts"][1]["correction_validation"].update(
                        mode="whole_chapter", passed=True, errors=[],
                    )
                    result["accepted"] = True
                    self.assertTrue(X.verify_history(result, request=request))

    def test_extra_corrections_and_wrong_round_count_fail_replay(self) -> None:
        request, valid = base("0.3")
        result = X.extract_chapter(request, ScriptedModel(bad_anchor(valid), valid))
        self.assertTrue(result["accepted"])
        changed = copy.deepcopy(result)
        changed["correction_rounds_used"] = 0
        self.assertTrue(X.verify_history(changed, request=request))
        result["attempts"].append(copy.deepcopy(result["attempts"][1]))
        result["correction_rounds_used"] = 2
        self.assertTrue(X.verify_history(result, request=request))

    def test_correction_cannot_be_relabelled_as_a_successful_initial_attempt(self) -> None:
        request, result = self.rejected_rewrite("0.2")
        result["attempts"].pop(0)
        result["attempts"][0]["kind"] = "initial"
        result["correction_rounds_used"] = 0
        result["accepted"] = True
        self.assertTrue(X.verify_history(result, request=request))
        result["attempts"][0].pop("correction_validation")
        self.assertTrue(X.verify_history(result, request=request))

    def test_legacy_histories_keep_their_original_acceptance_rule(self) -> None:
        for version in ("0.2", "0.3"):
            with self.subTest(version=version):
                # Produced with the unchanged renderer/extraction at 56198e1,
                # using scripted responses. These carry real legacy prompts,
                # not new prompts with their version labels altered.
                fixture = load(HERE.parent / "ingestion" / "fixtures" / "chapter-correction-history" / f"legacy-{version}.json")
                self.assertTrue(fixture["result"]["accepted"])
                self.assertEqual(X.verify_history(fixture["result"], request=fixture["request"]), [])


if __name__ == "__main__":
    unittest.main()
