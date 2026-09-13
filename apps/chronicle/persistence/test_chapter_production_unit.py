"""Local repair and carried-forward uncertainty acceptance regressions."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import chapter_production as production
from common import PersistenceError, sha256_json
from test_staged_chapter_contract_unit import fixture, request_for_text


def patch(path, before, value, *, op="replace"):
    return {"op": op, "path": path, "before_sha256": sha256_json(before), "value": value}


def metadata_collections(candidate):
    return {
        **{f"/bundle/{key}": candidate["bundle"][key] for key in ("entities", "events", "claims")},
        **{f"/{key}": candidate[key] for key in ("mentions", "record_sources", "warnings")},
        **{f"/reading/{key}": candidate["reading"][key] for key in ("units", "warnings")},
        **{f"/person_states/{key}": candidate["person_states"][key] for key in (
            "phases", "phase_orders", "unit_phases", "facts", "continuities", "disagreements")},
    }


class ChapterPatchTests(unittest.TestCase):
    def setUp(self):
        self.request, self.candidate = fixture()

    def test_every_model_sees_exact_block_text_and_body_annotation_boundaries(self):
        text = "𠮷曰〔某〕，正文。〈引文始〈注中注〉\n\n續引文〉後段正文。"
        request = request_for_text(text)
        original = copy.deepcopy(request)
        for step in production.STEPS:
            with self.subTest(step=step):
                prompt = production.build_prompt(step, request, {}, max_chars=262144)
                source = json.loads(next(line[7:] for line in prompt.splitlines() if line.startswith("SOURCE=")))
                self.assertEqual(source["normalized_text"], text)
                self.assertEqual("".join(block["text"] for block in source["blocks"]), text)
                fragments = source["source_scope"]["fragments"]
                self.assertEqual("".join(f["text"] for f in fragments if f["role"] == "body"),
                                 "𠮷曰〔某〕，正文。後段正文。")
                self.assertEqual("".join(f["text"] for f in fragments if f["role"] == "annotation"),
                                 "〈引文始〈注中注〉\n\n續引文〉")
                for block in source["blocks"]:
                    view = {key: value for key, value in block.items() if key != "text"}
                    self.assertIn(view, original["blocks"])
                self.assertEqual(request, original)
                self.assertEqual(production.build_prompt(step, request, {}, max_chars=len(prompt)), prompt)
                with self.assertRaisesRegex(PersistenceError, "no source/history truncation"):
                    production.build_prompt(step, request, {}, max_chars=len(prompt) - 1)

    def test_model_source_text_uses_chapter_relative_bounds_after_another_chapter(self):
        import chapter_plan
        import chapter_contract
        text = "# 史書\n\n## 甲傳\n\n甲任太守。\n\n## 乙傳\n\n乙任將軍。〈注稱別說。〉"
        locator = {"revision_id": "source-view-test", "source_sha256": chapter_contract.sha256_text(text),
                   "normalized_sha256": chapter_contract.sha256_text(text)}
        plan = chapter_plan.plan_chapters(text, locator, "two.md")
        request = chapter_plan.build_chapter_request(plan, 1, text, candidate_version="0.4")
        self.assertGreater(request["chapter_start"], 0)
        prompt = production.build_prompt("extraction", request, {}, max_chars=262144)
        source = json.loads(next(line[7:] for line in prompt.splitlines() if line.startswith("SOURCE=")))
        displayed = "".join(block["text"] for block in source["blocks"])
        self.assertIn("乙任將軍。", displayed)
        self.assertNotIn("甲任太守。", displayed)
        self.assertEqual(displayed, request["normalized_text"])

    def test_model_source_view_rejects_bad_bounds_instead_of_silently_slicing(self):
        for bounds in ((-1, 1), (0, 100000), (2, 1), (True, 1)):
            request = copy.deepcopy(self.request)
            request["blocks"][0].update(start=bounds[0], end=bounds[1])
            with self.subTest(bounds=bounds), self.assertRaisesRegex(PersistenceError, "chapter-relative bounds"):
                production.build_prompt("translation", request, {}, max_chars=262144)

    def test_model_schema_contains_all_referenced_extraction_and_linking_rules(self):
        extraction = {key: copy.deepcopy(self.candidate[key]) for key in (
            "chapter_id", "bundle", "mentions", "record_sources", "person_states", "warnings")}
        extraction["person_states"].pop("unit_phases")
        linking = {
            "chapter_id": self.candidate["chapter_id"],
            "translation_links": [{key: copy.deepcopy(value) for key, value in block.items() if key != "text"}
                                  for block in self.candidate["translation"]["blocks"]],
            "reading": copy.deepcopy(self.candidate["reading"]),
            "unit_phases": copy.deepcopy(self.candidate["person_states"]["unit_phases"]),
        }
        for step, value in (("extraction", extraction), ("linking", linking)):
            with self.subTest(step=step):
                prompt = production.build_prompt(step, self.request, {}, max_chars=262144)
                schema = json.loads(next(line[7:] for line in prompt.splitlines() if line.startswith("SCHEMA=")))
                # Validate using only what the remote model actually sees:
                # no repository registry or external-resource retriever.
                validator = Draft202012Validator(schema)
                self.assertEqual(list(validator.iter_errors(value)), [])
                def check_references(node):
                    if isinstance(node, dict):
                        if "$ref" in node:
                            self.assertTrue(node["$ref"].startswith("#/$defs/"))
                            self.assertIn(node["$ref"].split("/")[-1], schema["$defs"])
                        for child in node.values():
                            check_references(child)
                    elif isinstance(node, list):
                        for child in node:
                            check_references(child)
                check_references(schema)
                broken = copy.deepcopy(value)
                if step == "extraction":
                    broken["bundle"]["entities"][0]["temp_id"] = "ent_zhouyu"
                    del broken["bundle"]["schema_version"]
                else:
                    del broken["translation_links"][0]["entity_refs"][0]["ref"]
                self.assertTrue(list(validator.iter_errors(broken)))

    def test_prompt_is_stable_when_jsonb_changes_object_key_order(self):
        first = {"candidate": self.candidate, "history": [], "candidate_sha256": sha256_json(self.candidate)}
        def reorder(value):
            if isinstance(value, dict):
                return {key: reorder(value[key]) for key in reversed(list(value))}
            if isinstance(value, list):
                return [reorder(item) for item in value]
            return value
        self.assertEqual(
            production.build_prompt("review", self.request, first, max_chars=262144),
            production.build_prompt("review", reorder(self.request), reorder(first), max_chars=262144),
        )

    def test_step_retry_preserves_complete_raw_result_and_errors_with_a_hard_limit(self):
        prompt = production.build_prompt("extraction", self.request, {}, max_chars=262144)
        previous = {"output_sha256": "a" * 64, "raw_text": '{"wrong": "𠮷\\n完整返回"}',
                    "validation_errors": ["/bundle/entities/0/kind: entity was expected", "最后一项错误"]}
        original = copy.deepcopy(previous)
        retry = production.retry_prompt(prompt, previous, max_chars=262144)
        self.assertTrue(retry.startswith(prompt + "\n"))
        feedback = json.loads(next(line.removeprefix("PREVIOUS_ATTEMPT=") for line in retry.splitlines()
                                   if line.startswith("PREVIOUS_ATTEMPT=")))
        self.assertEqual(feedback, previous)
        self.assertEqual(production.retry_prompt(prompt, previous, max_chars=len(retry)), retry)
        with self.assertRaisesRegex(production.RetryPromptLimitExceeded, "no result or error truncation"):
            production.retry_prompt(prompt, previous, max_chars=len(retry) - 1)
        self.assertEqual(previous, original)

    def assert_rejected_unchanged(self, patches, message=None):
        original = copy.deepcopy(self.candidate)
        with self.assertRaisesRegex(PersistenceError, message or ".+"):
            production.apply_patches(self.candidate, patches)
        self.assertEqual(self.candidate, original)

    def test_array_removal_cannot_retarget_a_sibling_record_field_in_either_order(self):
        entities = self.candidate["bundle"]["entities"]
        patches = [
            patch("/bundle/entities/0", entities[0], None, op="remove"),
            patch("/bundle/entities/1/canonical_name", entities[1]["canonical_name"], "周公瑾"),
        ]
        for ordered in (patches, list(reversed(patches))):
            with self.subTest(order=[item["path"] for item in ordered]):
                self.assert_rejected_unchanged(ordered, "array removal")

    def test_nested_array_removal_cannot_retarget_a_sibling_field(self):
        mentions = self.candidate["bundle"]["entities"][0]["mentions"]
        patches = [
            patch("/bundle/entities/0/mentions/0", mentions[0], None, op="remove"),
            patch("/bundle/entities/0/mentions/1/text", mentions[1]["text"], "孫伯符"),
        ]
        for ordered in (patches, list(reversed(patches))):
            with self.subTest(order=[item["path"] for item in ordered]):
                self.assert_rejected_unchanged(ordered, "array removal")

    def test_removal_does_not_block_an_independent_collection_edit(self):
        entities = self.candidate["bundle"]["entities"]
        original = copy.deepcopy(self.candidate)
        fact = self.candidate["person_states"]["facts"][0]
        result = production.apply_patches(self.candidate, [
            patch("/bundle/entities/0", entities[0], None, op="remove"),
            patch("/person_states/facts/0", fact, copy.deepcopy(fact)),
        ])
        self.assertEqual(result["bundle"]["entities"], original["bundle"]["entities"][1:])
        self.assertEqual(result["person_states"], original["person_states"])
        self.assertEqual(self.candidate, original)

    def test_whole_metadata_objects_and_collections_cannot_be_replaced_or_removed(self):
        containers = {
            **metadata_collections(self.candidate),
            **{f"/{key}": self.candidate[key] for key in ("bundle", "reading", "person_states")},
        }
        for path, value in containers.items():
            for operation, replacement in (("replace", copy.deepcopy(value)),
                                           ("replace", [] if isinstance(value, list) else {}),
                                           ("remove", None)):
                with self.subTest(path=path, operation=operation, empty=not replacement):
                    self.assert_rejected_unchanged([patch(path, value, replacement, op=operation)])

    def test_missing_whole_collection_cannot_be_added(self):
        del self.candidate["person_states"]["facts"]
        self.assert_rejected_unchanged([patch("/person_states/facts", None, [], op="add")])

    def test_record_fields_records_append_and_prose_remain_editable(self):
        original = copy.deepcopy(self.candidate)
        entities = self.candidate["bundle"]["entities"]
        replacement = {**entities[1], "canonical_name": "周公瑾"}
        appended = {**entities[0], "temp_id": "ent_099"}
        result = production.apply_patches(self.candidate, [
            patch("/bundle/entities/0/description", entities[0]["description"], "字伯符。"),
            patch("/bundle/entities/1", entities[1], replacement),
            patch("/bundle/entities/-", None, appended, op="add"),
            patch("/translation/blocks/0/text", self.candidate["translation"]["blocks"][0]["text"], "连贯的白话正文。"),
        ])
        self.assertEqual(result["bundle"]["entities"][0]["description"], "字伯符。")
        self.assertEqual(result["bundle"]["entities"][1], replacement)
        self.assertEqual(result["bundle"]["entities"][-1], appended)
        self.assertEqual(result["translation"]["blocks"][0]["text"], "连贯的白话正文。")
        self.assertEqual([b["block_id"] for b in result["translation"]["blocks"]],
                         [b["block_id"] for b in original["translation"]["blocks"]])
        self.assertEqual(self.candidate, original)

    def test_array_add_must_append_without_inserting_between_records(self):
        entities = self.candidate["bundle"]["entities"]
        appended = {**entities[0], "temp_id": "ent_099"}
        for index in ("-", str(len(entities))):
            with self.subTest(index=index):
                result = production.apply_patches(self.candidate, [
                    patch(f"/bundle/entities/{index}", None, appended, op="add")])
                self.assertEqual(result["bundle"]["entities"], entities + [appended])
        self.assert_rejected_unchanged([patch("/bundle/entities/1", None, appended, op="add")], "append")

    def test_before_hash_checks_are_atomic(self):
        blocks = self.candidate["translation"]["blocks"]
        changes = [patch("/translation/blocks/0/text", blocks[0]["text"], "已修正的正文。"),
                   patch("/translation/blocks/1/text", "不是当前版本", "错误修正。")]
        self.assert_rejected_unchanged(changes, "before_sha256")

    def test_noop_repair_cannot_create_a_new_candidate_version(self):
        block = self.candidate["translation"]["blocks"][0]
        entity = self.candidate["bundle"]["entities"][0]
        self.assert_rejected_unchanged([
            patch("/translation/blocks/0/text", block["text"], block["text"]),
            patch("/bundle/entities/0", entity, dict(reversed(list(entity.items())))),
        ], "must change")

    def test_translation_blocks_identity_and_order_are_frozen(self):
        blocks = self.candidate["translation"]["blocks"]
        for change in (
            patch("/translation/blocks", blocks, list(reversed(blocks))),
            patch("/translation/blocks/0", blocks[0], None, op="remove"),
            patch("/translation/blocks/0/block_id", blocks[0]["block_id"], "tr_changed"),
            patch("/translation/blocks/0/text", blocks[0]["text"], None, op="remove"),
        ):
            with self.subTest(path=change["path"]):
                self.assert_rejected_unchanged([change])

    def test_patch_hash_menu_exposes_records_and_append_but_never_whole_collections(self):
        targets = production.patch_targets(self.candidate)
        for path, items in metadata_collections(self.candidate).items():
            with self.subTest(path=path):
                self.assertNotIn(path, targets)
                self.assertEqual(targets[path + "/-"], sha256_json(None))
                for index, item in enumerate(items):
                    self.assertEqual(targets[path + f"/{index}"], sha256_json(item))
        for path in ("/bundle", "/reading", "/person_states", "/translation", "/translation/blocks"):
            self.assertNotIn(path, targets)
        for index, block in enumerate(self.candidate["translation"]["blocks"]):
            self.assertEqual(targets[f"/translation/blocks/{index}/text"], sha256_json(block["text"]))


class CarriedUncertaintyTests(unittest.TestCase):
    def setUp(self):
        self.request, self.candidate = fixture()
        self.target = "/translation/blocks/0/text"
        self.candidate["translation"]["blocks"][0]["text"] += "此处另有说法，尚不能确定。"
        self.history = [{"step": "review", "opinion": "原文存在异说，译文须保留限定。"}]
        self.previous = [{
            "id": "old-uncertainty", "type": "source_uncertainty", "target": self.target,
            "message": "原文有异说，当前叙述尚未保留限定", "evidence": ["b_001"], "represented": False,
        }]

    def current_issue(self, **changes):
        return {
            "id": "current-uncertainty", "type": "source_uncertainty", "target": self.target,
            "message": "当前段落已保留另有说法且尚不能确定的限定。", "evidence": ["b_001"],
            "represented": True, **changes,
        }

    def report(self, *, disposition="source_uncertainty", issues=None):
        return {
            "candidate_sha256": sha256_json(self.candidate), "history_sha256": sha256_json(self.history),
            "verdict": "pass",
            "coverage": [f["id"] for f in self.request["source_scope"]["fragments"] if f["role"] == "body"],
            "issues": [] if issues is None else issues,
            "dispositions": [{"issue_id": "old-uncertainty", "disposition": disposition,
                              "rationale": "已核查本轮版本与旧意见。", "evidence": ["b_001"]}],
        }

    def errors(self, report):
        return production.review_errors(report, request=self.request, candidate=self.candidate,
                                        history=self.history, previous_issues=self.previous)

    def test_old_uncertainty_cannot_disappear_by_merely_changing_its_disposition(self):
        for disposition in ("resolved", "source_uncertainty"):
            with self.subTest(disposition=disposition):
                report = self.report(disposition=disposition)
                errors = self.errors(report)
                self.assertTrue(errors)
                self.assertFalse(production.review_passes(report, errors=errors))

    def test_current_same_target_represented_uncertainty_with_source_evidence_can_pass(self):
        for disposition in ("resolved", "source_uncertainty"):
            with self.subTest(disposition=disposition):
                report = self.report(disposition=disposition, issues=[self.current_issue()])
                errors = self.errors(report)
                self.assertEqual(errors, [])
                self.assertTrue(production.review_passes(report, errors=errors))

    def test_current_expression_must_match_target_type_representation_and_source(self):
        for changes in ({"target": "/translation/blocks/1/text"}, {"represented": False},
                        {"evidence": []}, {"evidence": ["invented-source"]}, {"type": "processing_error"}):
            with self.subTest(changes=changes):
                report = self.report(issues=[self.current_issue(**changes)])
                errors = self.errors(report)
                self.assertTrue(errors)
                self.assertFalse(production.review_passes(report, errors=errors))

    def test_unresolved_uncertainty_can_be_reported_without_pretending_it_is_represented(self):
        report = self.report(disposition="unresolved")
        report["verdict"] = "revise"
        errors = self.errors(report)
        self.assertEqual(errors, [])
        self.assertFalse(production.review_passes(report, errors=errors))

    def test_uncertainty_evidence_cannot_approve_old_candidate_or_history(self):
        for key in ("candidate_sha256", "history_sha256"):
            with self.subTest(key=key):
                report = self.report(issues=[self.current_issue()])
                report[key] = "0" * 64
                errors = self.errors(report)
                self.assertTrue(errors)
                self.assertFalse(production.review_passes(report, errors=errors))

    def test_new_uncertainty_also_requires_evidence_for_its_claimed_representation(self):
        self.previous = []
        report = self.report(issues=[self.current_issue(evidence=[])])
        report["dispositions"] = []
        errors = self.errors(report)
        self.assertTrue(errors)
        self.assertFalse(production.review_passes(report, errors=errors))


class ChapterHistoryTests(unittest.TestCase):
    def test_history_exposes_each_draft_version_and_its_parent_without_mutable_aliases(self):
        _request, original = fixture()
        revised = copy.deepcopy(original)
        revised["translation"]["blocks"][0]["text"] += "另有说法，尚不能确定。"
        records = [{
            "artifact_type": "chapter-production-draft", "output_sha256": "a" * 64,
            "candidate": original, "candidate_sha256": sha256_json(original), "parent_sha256": None,
        }, {
            "artifact_type": "chapter-production-draft", "output_sha256": "b" * 64,
            "candidate": revised, "candidate_sha256": sha256_json(revised), "parent_sha256": "a" * 64,
        }]
        history = production.history_for_model(records)
        for expected, entry in zip(records, history):
            for key in ("candidate", "candidate_sha256", "parent_sha256"):
                self.assertEqual(entry[key], expected[key])
        original_history_sha = sha256_json(history)
        records[0]["candidate"]["translation"]["blocks"][0]["text"] = "篡改旧稿。"
        self.assertEqual(sha256_json(history), original_history_sha)
        self.assertNotEqual(sha256_json(production.history_for_model(records)), original_history_sha)

    def test_history_keeps_parse_failures_without_repeating_valid_response_envelopes(self):
        parsed = {"verdict": "revise"}
        records = [{"artifact_type": "chapter-production-step", "parsed": parsed,
                    "raw_text": "完整的原始 JSON", "prompt": "无须重复提示内容"},
                   {"artifact_type": "chapter-production-step", "parsed": None,
                    "raw_text": "中断后保留的半份输出", "status": "failed"}]
        history = production.history_for_model(records)
        self.assertEqual(history[0]["parsed"], parsed)
        self.assertNotIn("raw_text", history[0])
        self.assertNotIn("prompt", history[0])
        self.assertEqual(history[1]["raw_text"], records[1]["raw_text"])
        self.assertEqual(history[1]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
