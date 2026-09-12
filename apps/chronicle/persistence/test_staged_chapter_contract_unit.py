"""0.4 scope, frozen-subset validation, acceptance and assembly regressions."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import assembly as A
import chapter_contract as C
import chapter_plan as Plan
import person_state_contract as P
import person_state_review as Review
import reading_contract as R
import staged_chapter_contract as S
from common import PersistenceError, sha256_json

FIXTURES = HERE.parent / "ingestion" / "fixtures" / "c2r3-contract"
RUN = {"run_id": "staged-contract-test", "model": "fixture", "prompt_schema_version": "staged-v1"}


def fixture(*, annotation: bool = False) -> tuple[dict, dict]:
    request = json.loads((FIXTURES / "request.json").read_text())
    candidate = json.loads((FIXTURES / "candidate-valid.json").read_text())
    if annotation:
        note = "〈裴松之注：另一說，尚須考證。〉"
        start = len(request["normalized_text"])
        request["normalized_text"] += note
        request["blocks"].append({
            "block_id": "b_004", "kind": "body", "start": start,
            "end": len(request["normalized_text"]),
        })
        request["required_block_ids"].append("b_004")
        request["source_sha256"] = C.sha256_text(request["normalized_text"])
        request["normalized_sha256"] = C.sha256_text(request["normalized_text"])
    request["schema_versions"]["candidate"] = "0.4"
    request["chapter_start"] = 0
    request["chapter_end"] = len(request["normalized_text"])
    request["revision_normalized_sha256"] = request["normalized_sha256"]
    request["source_scope"] = S.build_source_scope(request)
    request["required_block_ids"] = request["source_scope"]["body_block_ids"][:]
    candidate["version"] = "0.4"
    candidate["source_scope"] = copy.deepcopy(request["source_scope"])
    return request, candidate


def receipt(request: dict, candidate: dict) -> dict:
    return {
        "schema": "chronicle.chapter-acceptance", "version": "0.1", "status": "accepted",
        "request_fingerprint": C.request_fingerprint(request),
        "candidate_sha256": sha256_json(candidate), "history_sha256": "a" * 64,
        "step_output_sha256s": ["b" * 64], "decision": {"kind": "automatic"},
    }


def request_for_text(text: str) -> dict:
    locator = {
        "revision_id": "revision-test", "source_sha256": C.sha256_text(text),
        "normalized_sha256": C.sha256_text(text),
    }
    plan = Plan.plan_chapters(text, locator, "scope.txt")
    return Plan.build_chapter_request(plan, 0, text, candidate_version="0.4")


class SourceScopeTests(unittest.TestCase):
    def test_nested_cross_paragraph_annotations_and_editorial_body_survive(self):
        text = "𠮷曰〔某〕，正文。〈引文始〈注中注〉\n\n續引文〉後段正文。"
        request = request_for_text(text)
        scope = request["source_scope"]
        body = "".join(text[f["start"]:f["end"]] for f in scope["fragments"] if f["role"] == "body")
        notes = "".join(text[f["start"]:f["end"]] for f in scope["fragments"] if f["role"] == "annotation")
        self.assertEqual(body, "𠮷曰〔某〕，正文。後段正文。")
        self.assertEqual(notes, "〈引文始〈注中注〉\n\n續引文〉")
        for fragment in scope["fragments"]:
            self.assertEqual(fragment["text_sha256"], C.sha256_text(text[fragment["start"]:fragment["end"]]))
        self.assertEqual(S.build_source_scope(request), scope)

    def test_unmatched_delimiters_never_drop_source_silently(self):
        for text in ("正文〈未完原注", "正文〉無起始", "正文〈一〈二〉"):
            with self.subTest(text=text), self.assertRaisesRegex(PersistenceError, "source_scope"):
                request_for_text(text)

    def test_only_annotations_cannot_enter_translation(self):
        with self.assertRaisesRegex(PersistenceError, "no translatable body"):
            request_for_text("〈原注而無正文〉")

    def test_untagged_commentary_is_retained_as_body(self):
        request = request_for_text("正文。\n\n注家續引，未加顯式標記。")
        self.assertEqual(request["required_block_ids"], request["source_scope"]["body_block_ids"])
        self.assertTrue(all(f["role"] == "body" for f in request["source_scope"]["fragments"]))

    def test_multichapter_origin_and_hash_bindings(self):
        text = "# 三國志\n\n## 甲傳\n\n甲曰。\n\n## 乙傳\n\n乙曰。〈注〉"
        locator = {"revision_id": "rev-origin", "source_sha256": C.sha256_text(text), "normalized_sha256": C.sha256_text(text)}
        plan = Plan.plan_chapters(text, locator, "two.md")
        request = Plan.build_chapter_request(plan, 1, text, candidate_version="0.4")
        self.assertGreater(request["chapter_start"], 0)
        self.assertEqual(request["normalized_sha256"], C.sha256_text(request["normalized_text"]))
        self.assertEqual(request["revision_normalized_sha256"], C.sha256_text(text))
        for f in request["source_scope"]["fragments"]:
            original = text[request["chapter_start"] + f["start"]:request["chapter_start"] + f["end"]]
            self.assertEqual(C.sha256_text(original), f["text_sha256"])


class StagedCandidateTests(unittest.TestCase):
    def test_annotation_not_required_but_body_still_required(self):
        request, candidate = fixture(annotation=True)
        self.assertTrue(S.validate_staged_candidate(request, candidate)["passed"])
        self.assertNotIn("b_004", request["required_block_ids"])
        candidate["translation"]["blocks"][-1]["source_block_ids"] = ["b_004"]
        errors = S.flatten_staged_errors(S.validate_staged_candidate(request, candidate))
        self.assertTrue(any("not body scope" in error for error in errors))
        self.assertTrue(any("misses required source blocks" in error for error in errors))

    def test_scope_and_required_ids_cannot_be_rewritten_by_candidate_or_request(self):
        request, candidate = fixture()
        for mutated in ("candidate_scope", "request_scope", "required"):
            r, c = copy.deepcopy(request), copy.deepcopy(candidate)
            if mutated == "candidate_scope":
                c["source_scope"]["fragments"][0]["role"] = "annotation"
            elif mutated == "request_scope":
                r["source_scope"]["body_block_ids"].pop()
            else:
                r["required_block_ids"].pop()
            with self.subTest(mutated=mutated):
                self.assertFalse(S.validate_staged_candidate(r, c)["passed"])

    def test_frozen_state_subject_typing_remains_enforced(self):
        request, candidate = fixture()
        candidate["person_states"]["facts"][0]["person_ref"]["ref"] = "ent_003"  # Office, not person.
        report = S.validate_staged_candidate(request, candidate)
        self.assertFalse(report["passed"])
        self.assertTrue(report["person_states"]["errors"]["person_state_types"])

    def test_frozen_candidate_does_not_inherit_new_coverage(self):
        request, candidate = fixture(annotation=True)
        old = S._legacy_candidate(candidate, "0.3")
        old_request = copy.deepcopy(request)
        old_request["schema_versions"]["candidate"] = "0.3"
        old_request["required_block_ids"].append("b_004")
        self.assertFalse(P.validate_person_state_candidate(old_request, old)["passed"])

    def test_full_staged_request_fingerprint_rejects_input_drift(self):
        request, _ = fixture()
        original = C.request_fingerprint(request)
        request["title"] = "changed input"
        self.assertNotEqual(C.request_fingerprint(request), original)
        request["schema_versions"]["candidate"] = "0.3"
        old = C.request_fingerprint(request)
        request["title"] = "another unused old title"
        self.assertEqual(C.request_fingerprint(request), old)


class StagedAcceptanceTests(unittest.TestCase):
    def test_accepted_staged_artifact_assembles_and_keeps_state_review_required(self):
        request, candidate = fixture()
        accepted = S.accept_staged_candidate(request, candidate, producing_run=RUN, production_receipt=receipt(request, candidate))
        plan = Plan.plan_chapters(request["normalized_text"], request, "zhou-yu.txt")
        plan["chapters"][0]["chapter_id"] = request["chapter_id"]
        plan["chapters"][0]["blocks"] = [{
            **block,
            "content_sha256": C.sha256_text(request["normalized_text"][block["start"]:block["end"]]),
        } for block in request["blocks"]]
        plan["plan_sha256"] = Plan.plan_sha256_for(plan)
        assembled = A.assemble_chapters(accepted_artifacts=[accepted], chapter_plan=plan)
        self.assertEqual(assembled["report"]["candidate_version"], "0.4")
        self.assertEqual(len(assembled["reading_units"]), 3)
        state_assembly = {
            "person_states": assembled["person_states"],
            "evidence_manifests": assembled["person_state_evidence"],
            "report": assembled["report"]["person_state"],
        }
        review_plan = Review.build_person_state_review_plan(
            job_id="019535d9-3df7-7001-8000-000000000001",
            revision_id=request["revision_id"], accepted_artifacts=[accepted],
            assembly=state_assembly, resolution_hashes=[], base_catalog_sha="e" * 64,
        )
        self.assertTrue(review_plan["candidate_keys"])

    def test_staged_scope_origin_cannot_drift_from_plan(self):
        request, candidate = fixture()
        plan = Plan.plan_chapters(request["normalized_text"], request, "zhou-yu.txt")
        plan["chapters"][0]["chapter_id"] = request["chapter_id"]
        plan["plan_sha256"] = Plan.plan_sha256_for(plan)
        request["chapter_start"] += 1
        request["chapter_end"] += 1
        request["source_scope"] = S.build_source_scope(request)
        candidate["source_scope"] = copy.deepcopy(request["source_scope"])
        accepted = S.accept_staged_candidate(request, candidate, producing_run=RUN, production_receipt=receipt(request, candidate))
        with self.assertRaisesRegex(PersistenceError, "source scope origin"):
            A.assemble_chapters(accepted_artifacts=[accepted], chapter_plan=plan)

    def test_actual_version_hash_and_units_include_receipt(self):
        request, candidate = fixture()
        accepted = S.accept_staged_candidate(request, candidate, producing_run=RUN, production_receipt=receipt(request, candidate))
        self.assertEqual(accepted["version"], "0.4")
        self.assertEqual(accepted["candidate"], candidate)
        core = {k: v for k, v in accepted.items() if k not in ("artifact_sha256", "reading_units")}
        self.assertEqual(accepted["artifact_sha256"], sha256_json(core))
        unit = accepted["reading_units"][0]
        self.assertEqual(unit["unit_id"], R.unit_id_for(revision_id=request["revision_id"], chapter_id=request["chapter_id"], block_id=unit["block_id"], artifact_sha256=accepted["artifact_sha256"]))
        other_receipt = receipt(request, candidate)
        other_receipt["history_sha256"] = "c" * 64
        other = S.accept_staged_candidate(request, candidate, producing_run=RUN, production_receipt=other_receipt)
        self.assertNotEqual(other["reading_units"][0]["unit_id"], unit["unit_id"])
        self.assertEqual(A._validate_accepted_chapter_artifact(accepted, position=0)["artifact_version"], "0.4")

    def test_receipt_cannot_approve_a_different_candidate_or_request(self):
        request, candidate = fixture()
        original = receipt(request, candidate)
        for key, value in (("candidate_sha256", "0" * 64), ("request_fingerprint", "0" * 64), ("status", "pending"), ("step_output_sha256s", []), ("decision", {})):
            changed = {**original, key: value}
            with self.subTest(key=key), self.assertRaises(PersistenceError):
                S.accept_staged_candidate(request, candidate, producing_run=RUN, production_receipt=changed)

    def test_artifact_core_tampering_and_version_relabel_fail(self):
        request, candidate = fixture()
        accepted = S.accept_staged_candidate(request, candidate, producing_run=RUN, production_receipt=receipt(request, candidate))
        accepted["production_receipt"]["history_sha256"] = "d" * 64
        with self.assertRaisesRegex(PersistenceError, "artifact core"):
            A._validate_accepted_chapter_artifact(accepted, position=0)


if __name__ == "__main__":
    unittest.main()
