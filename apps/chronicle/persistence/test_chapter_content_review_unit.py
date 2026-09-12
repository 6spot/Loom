"""Version/coverage regressions for the human chapter-content boundary."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import chapter_content_review as review
from common import PersistenceConflict, PersistenceError, sha256_json
from test_staged_chapter_contract_unit import fixture


def packet_fixture(**overrides):
    request, candidate = fixture()
    values = {
        "job_id": "11111111-1111-7111-8111-111111111111", "chunk_id": "22222222-2222-7222-8222-222222222222",
        "request": request, "candidate": candidate,
        "history": [{"step": "review", "model": "fixture-a", "raw_text": "先前指出主语应为吴军"},
                    {"step": "review", "model": "fixture-b", "raw_text": "复核改判先主，仍需解释相反意见"}],
        "issues": [{"id": "subject-reversal", "type": "processing_error", "target": "/translation/blocks/0/text",
                    "message": "对同一主语的意见发生反转", "evidence": ["保留前后两轮意见"]}],
        "validation_errors": [], "pipeline_fingerprint": "a" * 64, "step_output_sha256s": [],
    }
    values.update(overrides)
    return review.build_review_packet(**values)


def decision_for(packet, **overrides):
    result = {
        "decision": "accept", "plan_fingerprint": packet["plan_fingerprint"],
        "candidate_sha256": packet["candidate_sha256"], "history_sha256": packet["history_sha256"],
        "rationale": "已结合整章核查当前版本，并逐项说明前后异议",
        "issue_dispositions": [{"issue_id": issue["id"], "disposition": "rejected", "rationale": "已核对所指原文及完整前序记录"} for issue in packet["issues"]],
    }
    result.update(overrides)
    return result


class ChapterContentDecisionUnitTests(unittest.TestCase):
    def test_fingerprint_binds_every_original_opinion_and_full_request(self):
        packet = packet_fixture()
        changed_history = copy.deepcopy(packet["history"])
        changed_history[0]["raw_text"] = "丢失了最初的相反意见"
        self.assertNotEqual(packet["plan_fingerprint"], packet_fixture(history=changed_history)["plan_fingerprint"])
        request = copy.deepcopy(packet["request"])
        request["chapter_start"] += 1
        self.assertNotEqual(packet["request_fingerprint"], packet_fixture(request=request)["request_fingerprint"])

    def test_accept_binds_unchanged_valid_candidate_and_complete_issue_coverage(self):
        packet = packet_fixture()
        self.assertTrue(review.validation_report(packet)["valid"])
        fixed = review.normalize_content_decision(packet, decision_for(packet))
        self.assertEqual(fixed["candidate_sha256"], sha256_json(packet["candidate"]))
        self.assertEqual(fixed["decision"], "accept")
        self.assertNotIn("patches", fixed)
        self.assertEqual(fixed["history_sha256"], sha256_json(packet["history"]))

    def test_a_pass_cannot_carry_even_an_empty_patch_list(self):
        packet = packet_fixture()
        with self.assertRaisesRegex(PersistenceError, "must not contain patches"):
            review.normalize_content_decision(packet, decision_for(packet, patches=[]))

    def test_old_candidate_or_history_approval_is_rejected(self):
        packet = packet_fixture()
        for field in ("candidate_sha256", "history_sha256", "plan_fingerprint"):
            with self.subTest(field=field), self.assertRaises(PersistenceConflict):
                review.normalize_content_decision(packet, decision_for(packet, **{field: "0" * 64}))

    def test_omitted_duplicate_and_invented_dispositions_fail(self):
        packet = packet_fixture()
        good = decision_for(packet)["issue_dispositions"][0]
        for items in ([], [good, good], [{**good, "issue_id": "missing"}]):
            with self.subTest(items=items), self.assertRaises(PersistenceError):
                review.normalize_content_decision(packet, decision_for(packet, issue_dispositions=items))

    def test_processing_error_cannot_become_source_uncertainty(self):
        packet = packet_fixture()
        decision = decision_for(packet)
        decision["issue_dispositions"][0]["disposition"] = "source_uncertainty"
        with self.assertRaisesRegex(PersistenceError, "cannot be relabelled"):
            review.normalize_content_decision(packet, decision)

    def test_source_uncertainty_can_be_explicitly_retained(self):
        packet = packet_fixture(issues=[{"id": "attribution", "type": "source_uncertainty", "target": "叙述归属", "message": "史料自己保留疑问", "evidence": "原文称或曰"}])
        decision = decision_for(packet)
        decision["issue_dispositions"][0]["disposition"] = "source_uncertainty"
        self.assertEqual(review.normalize_content_decision(packet, decision)["issue_dispositions"][0]["disposition"], "source_uncertainty")

    def test_missing_or_mechanically_invalid_candidate_cannot_be_accepted(self):
        for packet in (packet_fixture(candidate=None), packet_fixture(validation_errors=["unresolved reference"])):
            with self.subTest(candidate=packet["candidate_sha256"]), self.assertRaises(PersistenceConflict):
                review.normalize_content_decision(packet, decision_for(packet))

    def test_reject_retains_reasons_without_claiming_acceptance(self):
        packet = packet_fixture(candidate=None)
        fixed = review.normalize_content_decision(packet, decision_for(packet, decision="reject"))
        self.assertEqual(fixed["decision"], "reject")
        self.assertIsNone(fixed["candidate_sha256"])

    def test_patch_fields_are_not_a_backdoor_for_full_replacement(self):
        packet = packet_fixture()
        for fields in ({"content": packet["candidate"]}, {"candidate": packet["candidate"]}, {"decision": "same_entity"}):
            with self.subTest(fields=list(fields)), self.assertRaises(PersistenceError):
                review.normalize_content_decision(packet, decision_for(packet, **fields))


if __name__ == "__main__":
    unittest.main()
