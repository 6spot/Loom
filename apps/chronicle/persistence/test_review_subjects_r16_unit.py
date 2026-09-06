"""R16/R18 regression for proven review groups and operator review batches."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import review_subjects as S  # noqa: E402
from common import PersistenceConflict, PersistenceError, canonical_json_bytes, sha256_json  # noqa: E402


def _resolution(
    left_bundle: str,
    entity_pairs: list[tuple[str, str]] | None = None,
    event_pairs: list[tuple[str, str]] | None = None,
) -> dict:
    def links(prefix: str, pairs: list[tuple[str, str]], kind: str) -> list[dict]:
        return [
            {
                "candidate_id": f"{prefix}_{index:03d}",
                "left": {"bundle": left_bundle, "ref": left},
                "right": {"bundle": "new", "ref": right},
                "decision": "uncertain",
                "confidence": 0.5,
                "rationale": "source-bounded review required",
                "signals": [f"{kind} signal {left}/{right}"],
            }
            for index, (left, right) in enumerate(pairs, 1)
        ]

    return {
        "schema": "chronicle.resolution-links",
        "version": "0.1",
        "left_bundle": {
            "label": left_bundle,
            "source_ref": "src_001",
            "source_title": left_bundle,
        },
        "right_bundle": {
            "label": "new",
            "source_ref": "src_001",
            "source_title": "new",
        },
        "entity_links": links("ec", entity_pairs or [], "entity"),
        "event_links": links("vc", event_pairs or [], "event"),
        "warnings": [],
    }


def _catalog(
    entity_groups: list[tuple[str, list[tuple[str, str]]]] | None = None,
    event_groups: list[tuple[str, list[tuple[str, str]]]] | None = None,
) -> dict:
    def records(groups: list[tuple[str, list[tuple[str, str]]]]) -> list[dict]:
        return [
            {
                "canonical_id": canonical_id,
                "representations": [
                    {"bundle": bundle, "ref": ref} for bundle, ref in representations
                ],
            }
            for canonical_id, representations in groups
        ]

    return {
        "schema": "chronicle.canonical-catalog",
        "version": "0.1",
        "canonical_entities": records(entity_groups or []),
        "canonical_events": records(event_groups or []),
    }


def _within(
    entity_links: list[tuple[str, str, str]] | None = None,
    event_links: list[tuple[str, str, str]] | None = None,
) -> dict:
    def links(values: list[tuple[str, str, str]], kind: str) -> list[dict]:
        return [
            {
                "candidate_id": f"wc_{index:03d}",
                "kind": kind,
                "left": {"ref": left, "chunk_index": 0},
                "right": {"ref": right, "chunk_index": 1},
                "decision": decision,
                "confidence": 1.0 if decision.startswith("same_") else 0.5,
                "rationale": "test",
                "signals": [],
            }
            for index, (left, right, decision) in enumerate(values, 1)
        ]

    return {
        "entity_links": links(entity_links or [], "entity"),
        "event_links": links(event_links or [], "event"),
    }


class ReviewSubjectTests(unittest.TestCase):
    def test_published_and_proven_new_components_collapse_pairwise_debt(self) -> None:
        first = _resolution(
            "old-a", entity_pairs=[("ent_a", "ent_n1"), ("ent_a", "ent_n2")]
        )
        second = _resolution(
            "old-b", entity_pairs=[("ent_b", "ent_n1"), ("ent_b", "ent_n2")]
        )
        subjects = S.build_review_subjects(
            [first, second],
            catalog=_catalog(
                entity_groups=[
                    ("canon-cao", [("old-a", "ent_a"), ("old-b", "ent_b")])
                ]
            ),
            within_book_links=_within(
                entity_links=[("ent_n1", "ent_n2", "same_entity")]
            ),
        )
        self.assertEqual(len(subjects), 1)
        subject = subjects[0]
        self.assertEqual(subject["link_kind"], "entity")
        self.assertEqual(subject["group_count"], 1)
        self.assertEqual(subject["member_count"], 4)
        self.assertEqual(subject["groups"][0]["member_count"], 4)

    def test_unproven_incoming_refs_share_one_operator_batch_not_equivalence(self) -> None:
        resolution = _resolution(
            "old-a",
            entity_pairs=[
                ("ent_a", "ent_zhuge_1"),
                ("ent_a", "ent_zhuge_2"),
                ("ent_a", "ent_zhuge_3"),
            ],
        )
        subjects = S.build_review_subjects(
            [resolution],
            catalog=_catalog(entity_groups=[("canon-zhuge", [("old-a", "ent_a")])]),
            within_book_links=_within(),
        )
        self.assertEqual(len(subjects), 1)
        subject = subjects[0]
        self.assertEqual(subject["group_count"], 3)
        self.assertEqual(subject["member_count"], 3)
        self.assertEqual(
            sorted(group["member_count"] for group in subject["groups"]), [1, 1, 1]
        )
        roots = {group["component_root"] for group in subject["groups"]}
        self.assertEqual(roots, {"ent_zhuge_1", "ent_zhuge_2", "ent_zhuge_3"})

    def test_different_published_canonical_ids_remain_separate_batches(self) -> None:
        resolution = _resolution(
            "old-a",
            entity_pairs=[("ent_a", "ent_new_a"), ("ent_b", "ent_new_b")],
        )
        subjects = S.build_review_subjects(
            [resolution],
            catalog=_catalog(
                entity_groups=[
                    ("canon-a", [("old-a", "ent_a")]),
                    ("canon-b", [("old-a", "ent_b")]),
                ]
            ),
            within_book_links=_within(),
        )
        self.assertEqual(len(subjects), 2)
        self.assertEqual(sorted(item["group_count"] for item in subjects), [1, 1])

    def test_uncertain_within_book_link_does_not_create_proven_group(self) -> None:
        resolution = _resolution(
            "old-a", entity_pairs=[("ent_a", "ent_n1"), ("ent_a", "ent_n2")]
        )
        subjects = S.build_review_subjects(
            [resolution],
            catalog=_catalog(entity_groups=[("canon-cao", [("old-a", "ent_a")])]),
            within_book_links=_within(
                entity_links=[("ent_n1", "ent_n2", "uncertain")]
            ),
        )
        self.assertEqual(len(subjects), 1)
        self.assertEqual(subjects[0]["group_count"], 2)

    def test_event_related_occurrence_stays_two_groups_inside_one_batch(self) -> None:
        resolution = _resolution(
            "old-a", event_pairs=[("evt_a", "evt_n1"), ("evt_a", "evt_n2")]
        )
        catalog = _catalog(event_groups=[("canon-event", [("old-a", "evt_a")])])
        same = S.build_review_subjects(
            [resolution],
            catalog=catalog,
            within_book_links=_within(
                event_links=[("evt_n1", "evt_n2", "same_occurrence")]
            ),
        )
        self.assertEqual(len(same), 1)
        self.assertEqual(same[0]["group_count"], 1)
        related = S.build_review_subjects(
            [resolution],
            catalog=catalog,
            within_book_links=_within(
                event_links=[("evt_n1", "evt_n2", "related_occurrence")]
            ),
        )
        self.assertEqual(len(related), 1)
        self.assertEqual(related[0]["group_count"], 2)

    def test_negative_constraint_inside_proven_component_fails_closed(self) -> None:
        resolution = _resolution(
            "old-a", entity_pairs=[("ent_a", "ent_n1"), ("ent_a", "ent_n3")]
        )
        with self.assertRaises(PersistenceConflict):
            S.build_review_subjects(
                [resolution],
                catalog=_catalog(entity_groups=[("canon-cao", [("old-a", "ent_a")])]),
                within_book_links=_within(
                    entity_links=[
                        ("ent_n1", "ent_n2", "same_entity"),
                        ("ent_n2", "ent_n3", "same_entity"),
                        ("ent_n1", "ent_n3", "not_same"),
                    ]
                ),
            )

    def test_subject_identity_is_byte_deterministic_under_input_order(self) -> None:
        first = _resolution("old-a", entity_pairs=[("ent_a", "ent_n1")])
        second = _resolution("old-b", entity_pairs=[("ent_b", "ent_n2")])
        catalog = _catalog(
            entity_groups=[("canon-cao", [("old-b", "ent_b"), ("old-a", "ent_a")])]
        )
        a = S.build_review_subjects(
            [first, second], catalog=catalog, within_book_links=_within()
        )
        b = S.build_review_subjects(
            [copy.deepcopy(second), copy.deepcopy(first)],
            catalog=copy.deepcopy(catalog),
            within_book_links=_within(),
        )
        self.assertEqual(canonical_json_bytes(a), canonical_json_bytes(b))

    def test_default_decision_fans_out_to_every_group_candidate(self) -> None:
        resolution = _resolution(
            "old-a", entity_pairs=[("ent_a", "ent_n1"), ("ent_a", "ent_n2")]
        )
        subject = S.build_review_subjects(
            [resolution],
            catalog=_catalog(entity_groups=[("canon-cao", [("old-a", "ent_a")])]),
            within_book_links=_within(),
        )[0]
        payload = S.subject_payload(subject)
        payload["decision"] = {
            "decision": "same_entity",
            "confidence": 0.95,
            "rationale": "人工核对该批次全部逐字证据后确认均为同一人物",
        }
        expanded = S.decision_entries_for_payload(payload, status="resolved")
        expected = {
            f"{sha256_json(resolution)}:ec_001",
            f"{sha256_json(resolution)}:ec_002",
        }
        self.assertEqual(set(expanded), expected)
        self.assertTrue(
            all(item["decision"] == "same_entity" for item in expanded.values())
        )

    def test_group_override_affects_only_exception_group(self) -> None:
        resolution = _resolution(
            "old-a", entity_pairs=[("ent_a", "ent_n1"), ("ent_a", "ent_n2")]
        )
        subject = S.build_review_subjects(
            [resolution],
            catalog=_catalog(entity_groups=[("canon-cao", [("old-a", "ent_a")])]),
            within_book_links=_within(),
        )[0]
        payload = S.subject_payload(subject)
        groups = sorted(subject["groups"], key=lambda item: item["component_root"])
        exception = groups[1]
        payload["decision"] = {
            "decision": "same_entity",
            "confidence": 0.95,
            "rationale": "默认组经人工证据确认同一人物",
            "group_decisions": [
                {
                    "review_group_id": exception["review_group_id"],
                    "decision": "not_same",
                    "confidence": 0.9,
                    "rationale": "该候选组原文证据显示为另一人物",
                }
            ],
        }
        expanded = S.decision_entries_for_payload(payload, status="resolved")
        first_key = groups[0]["members"][0]["candidate_key"]
        second_key = groups[1]["members"][0]["candidate_key"]
        self.assertEqual(expanded[first_key]["decision"], "same_entity")
        self.assertEqual(expanded[second_key]["decision"], "not_same")

    def test_invalid_or_duplicate_group_override_fails_closed(self) -> None:
        resolution = _resolution("old-a", entity_pairs=[("ent_a", "ent_n1")])
        subject = S.build_review_subjects(
            [resolution],
            catalog=_catalog(entity_groups=[("canon-cao", [("old-a", "ent_a")])]),
            within_book_links=_within(),
        )[0]
        payload = S.subject_payload(subject)
        with self.assertRaises(PersistenceError):
            S.normalize_group_decisions(
                payload,
                [
                    {
                        "review_group_id": "missing",
                        "decision": "not_same",
                        "confidence": 0.9,
                        "rationale": "bad id",
                    }
                ],
            )
        group_id = subject["groups"][0]["review_group_id"]
        duplicate = {
            "review_group_id": group_id,
            "decision": "not_same",
            "confidence": 0.9,
            "rationale": "duplicate",
        }
        with self.assertRaises(PersistenceConflict):
            S.normalize_group_decisions(payload, [duplicate, duplicate])


if __name__ == "__main__":
    unittest.main()
