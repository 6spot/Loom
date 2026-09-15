"""Unit coverage for the independent person-history contract."""
from __future__ import annotations

import copy
import json
import unittest

import person_history_acceptance as acceptance
import person_history_contract as contract
from common import PersistenceError, sha256_json


PERSON = "person-zhou-yu"
FRIEND = "person-sun-quan"
PLACE = "place-jiangdong"


def context_fixture() -> dict:
    return {
        "schema": contract.CONTEXT_SCHEMA,
        "version": contract.VERSION,
        "source_selection": {
            "catalog_sha": "c" * 64,
            "publication_ids": ["publication-early", "publication-late"],
        },
        "target": {"person_id": PERSON, "name": "周瑜", "kind": "person"},
        "entities": {
            PERSON: {"name": "周瑜", "kind": "person"},
            FRIEND: {"name": "孙权", "kind": "person"},
            PLACE: {"name": "江东", "kind": "place"},
        },
        "events": {"event-red-cliffs": {"name": "赤壁战事"}},
        "sources": [
            {
                "source_id": "source-early",
                "publication_id": "publication-early",
                "evidence": [
                    {
                        "id": "e-early",
                        "relation": "support",
                        "attribution": "史料甲",
                        "note": "原文明确记载。",
                    }
                ],
            },
            {
                "source_id": "source-late",
                "publication_id": "publication-late",
                "evidence": [
                    {
                        "id": "e-late",
                        "relation": "support",
                        "attribution": "史料乙",
                        "note": "原文明确记载。",
                    }
                ],
            },
        ],
        "approved_conclusions": [
            {"id": "approved-office", "source_id": "source-early", "person_id": PERSON},
            {"id": "approved-action", "source_id": "source-late", "person_id": PERSON},
        ],
        "main_history_positions": [
            {
                "id": "history-late-a", "version_sha": "h" * 64,
                "paragraph_id": "main-1", "person_id": PERSON,
            },
            {
                "id": "history-late-b", "version_sha": "h" * 64,
                "paragraph_id": "main-2", "person_id": PERSON,
            },
        ],
    }


def summary_fixture() -> dict:
    return {
        "schema": f"{contract.SCHEMA}-summary",
        "version": contract.VERSION,
        "person_id": PERSON,
        "title": "周瑜生平概况",
        "overview": "以下概况只整理当前收录资料明确记载的内容。",
        "birth": None,
        "death": None,
        "coverage": {
            "statement": "根据当前收录资料整理的经历",
            "exhaustive": False,
            "source_ids": ["source-early", "source-late"],
            "publication_ids": ["publication-early", "publication-late"],
        },
        "phases": [
            {
                "id": "phase-early",
                "label": "早期经历",
                "year": 200,
                "period": None,
                "basis": ["e-early"],
                "relation_to_previous": "uncertain",
                "mapping_status": "unmapped",
                "mapping_position_ids": [],
                "mapping_reason": "主历史没有足够可靠的对应位置。",
            },
            {
                "id": "phase-late",
                "label": "晚期经历",
                "year": 208,
                "period": None,
                "basis": ["e-late"],
                "relation_to_previous": "after",
                "mapping_status": "ambiguous",
                "mapping_position_ids": ["history-late-a", "history-late-b"],
                "mapping_reason": "主历史存在两个可能对应段落，暂不强行唯一归并。",
            },
        ],
        "conclusions": [
            {
                "id": "conclusion-office",
                "person_id": PERSON,
                "dimension": "office",
                "phase_ids": ["phase-early"],
                "text": "周瑜在早期资料中被记为偏将军。",
                "value": "偏将军",
                "certainty": "clear",
                "qualification": "ordinary",
                "event_id": None,
                "related_entity_ids": [],
                "evidence": [
                    {
                        "id": "e-early",
                        "relation": "support",
                        "attribution": "史料甲",
                        "note": "原文明确记载。",
                    }
                ],
                "approved_conclusion_ids": ["approved-office"],
            },
            {
                "id": "conclusion-action",
                "person_id": PERSON,
                "dimension": "action",
                "phase_ids": ["phase-late"],
                "text": "来源记载周瑜参与赤壁战事。",
                "value": None,
                "certainty": "clear",
                "qualification": "ordinary",
                "event_id": "event-red-cliffs",
                "related_entity_ids": [PLACE],
                "evidence": [
                    {
                        "id": "e-late",
                        "relation": "support",
                        "attribution": "史料乙",
                        "note": "原文明确记载。",
                    }
                ],
                "approved_conclusion_ids": ["approved-action"],
            },
            {
                "id": "conclusion-person",
                "person_id": PERSON,
                "dimension": "related_person",
                "phase_ids": ["phase-late"],
                "text": "晚期资料同时提到周瑜与孙权的关系。",
                "value": None,
                "certainty": "uncertain",
                "qualification": "reported",
                "event_id": None,
                "related_entity_ids": [FRIEND],
                "evidence": [
                    {
                        "id": "e-late",
                        "relation": "supplement",
                        "attribution": "史料乙",
                        "note": "原文提及相关人物。",
                    }
                ],
                "approved_conclusion_ids": ["approved-action"],
            },
        ],
    }


def prose_fixture(summary: dict) -> dict:
    return {
        "schema": f"{contract.SCHEMA}-prose",
        "version": contract.VERSION,
        "person_id": PERSON,
        "summary_sha256": sha256_json(summary),
        "coverage": copy.deepcopy(summary["coverage"]),
        "paragraphs": [
            {
                "id": "paragraph-early",
                "phase_id": "phase-early",
                "segments": [
                    {
                        "text": "早期资料将周瑜记为偏将军。",
                        "conclusion_ids": ["conclusion-office"],
                        "event_id": None,
                        "related_entity_ids": [],
                    }
                ],
            },
            {
                "id": "paragraph-late",
                "phase_id": "phase-late",
                "segments": [
                    {
                        "text": "晚期资料记载周瑜参与赤壁战事，并提到孙权。",
                        "conclusion_ids": ["conclusion-action", "conclusion-person"],
                        "event_id": "event-red-cliffs",
                        "related_entity_ids": [PLACE, FRIEND],
                    }
                ],
            },
        ],
    }


class PersonHistoryContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = context_fixture()
        self.summary = summary_fixture()
        self.prose = prose_fixture(self.summary)

    def test_summary_and_prose_compile_with_explicit_mapping_and_unknown_dates(self):
        contract.validate_summary(self.summary, self.context)
        contract.validate_prose(self.prose, self.context, self.summary)
        publication = contract.compile_publication(self.context, self.summary, self.prose)
        self.assertIsNone(publication["birth"])
        self.assertIsNone(publication["death"])
        self.assertEqual("ambiguous", publication["phases"][1]["mapping_status"])
        self.assertEqual(2, len(publication["paragraphs"]))
        self.assertEqual("根据当前收录资料整理的经历", publication["coverage"]["statement"])

    def test_invalid_identity_coverage_state_and_phase_references_fail_closed(self):
        invalid = copy.deepcopy(self.summary)
        invalid["person_id"] = "same-name-but-unresolved"
        with self.assertRaisesRegex(PersistenceError, "fixed canonical person"):
            contract.validate_summary(invalid, self.context)

        invalid = copy.deepcopy(self.summary)
        invalid["coverage"]["statement"] = "完整生平"
        with self.assertRaisesRegex(PersistenceError, "根据当前收录资料整理的经历"):
            contract.validate_summary(invalid, self.context)

        invalid = copy.deepcopy(self.summary)
        invalid["conclusions"][0]["dimension"] = "action"
        invalid["conclusions"][0]["value"] = "偏将军"
        with self.assertRaisesRegex(PersistenceError, "action conclusion"):
            contract.validate_summary(invalid, self.context)

        invalid = copy.deepcopy(self.summary)
        invalid["phases"][1]["basis"] = ["missing-evidence"]
        with self.assertRaisesRegex(PersistenceError, "outside the frozen context"):
            contract.validate_summary(invalid, self.context)

        invalid = copy.deepcopy(self.summary)
        invalid["conclusions"][0]["evidence"] = [invalid["conclusions"][1]["evidence"][0]]
        with self.assertRaisesRegex(PersistenceError, "bound to its cited source evidence"):
            contract.validate_summary(invalid, self.context)

    def test_prose_must_cover_all_phases_and_only_reviewed_conclusions(self):
        invalid = copy.deepcopy(self.prose)
        invalid["paragraphs"][1]["phase_id"] = "phase-unknown"
        with self.assertRaisesRegex(PersistenceError, "unknown phase"):
            contract.validate_prose(invalid, self.context, self.summary)

        invalid = copy.deepcopy(self.prose)
        invalid["paragraphs"][1]["segments"][0]["conclusion_ids"] = ["invented"]
        with self.assertRaisesRegex(PersistenceError, "unreviewed conclusion"):
            contract.validate_prose(invalid, self.context, self.summary)

        invalid = copy.deepcopy(self.prose)
        invalid["paragraphs"] = invalid["paragraphs"][:1]
        with self.assertRaisesRegex(PersistenceError, "every ordered life phase"):
            contract.validate_prose(invalid, self.context, self.summary)

        invalid = copy.deepcopy(self.prose)
        invalid["paragraphs"][1]["segments"][0]["related_entity_ids"] = [PERSON]
        with self.assertRaisesRegex(PersistenceError, "not carried by its cited conclusion"):
            contract.validate_prose(invalid, self.context, self.summary)

    def test_prompts_hide_canonical_handles_and_comparisons_bind_fixed_candidates(self):
        forward, reverse = contract.model_reference_maps(self.context)
        self.assertEqual(PERSON, reverse[forward[PERSON]])
        prompt = contract.build_step_prompt("summary_generate", {"context": self.context})
        self.assertIn("不得用首次或末次出现推定", prompt)
        self.assertNotIn(PERSON, prompt)

        candidates = [
            {"candidate_sha256": "a" * 64, "content": self.summary},
            {"candidate_sha256": "b" * 64, "content": self.summary},
        ]
        comparison = {
            "schema": f"{contract.SCHEMA}-comparison",
            "version": contract.VERSION,
            "product": "summary",
            "candidate_set_sha256": sha256_json(candidates),
            "selected_sha256": "a" * 64,
            "selection_rationale": "候选甲的引用与覆盖说明完整。",
            "differences": [
                {
                    "candidate_sha256": "a" * 64,
                    "assessment": "selected",
                    "rationale": "引用完整。",
                    "evidence": ["e-early"],
                },
                {
                    "candidate_sha256": "b" * 64,
                    "assessment": "rejected",
                    "rationale": "不作为最终稿。",
                    "evidence": ["e-late"],
                },
            ],
            "disagreements": [],
        }
        contract.validate_comparison(comparison, self.context, "summary", candidates)
        comparison["candidate_set_sha256"] = "c" * 64
        with self.assertRaisesRegex(PersistenceError, "candidate set"):
            contract.validate_comparison(comparison, self.context, "summary", candidates)


class PersonHistoryAcceptanceTests(unittest.TestCase):
    def test_receipt_binds_reviewed_conclusions_and_content_hashes(self):
        content = {"schema": "chronicle.person-history-summary", "value": "概况"}
        receipt = acceptance.build_receipt(
            job_id="job-1",
            kind="summary",
            acceptance_type="policy_model_review",
            input_sha256="a" * 64,
            candidate_sha256="b" * 64,
            content=content,
            pipeline_fingerprint="c" * 64,
            model_output_sha256s=["d" * 64],
            model_opinion_sha256s=[],
            decision_reason="通过来源与身份边界检查。",
            reviewed_conclusion_ids=["conclusion-1"],
        )
        acceptance.validate_receipt(receipt)
        tampered = copy.deepcopy(receipt)
        tampered["reviewed_conclusion_ids"] = ["conclusion-2"]
        with self.assertRaisesRegex(PersistenceError, "receipt hash"):
            acceptance.validate_receipt(tampered)


if __name__ == "__main__":
    unittest.main()
