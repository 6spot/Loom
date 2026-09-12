"""Unit tests for the Chronicle C2-R3-T04 disagreement index compiler.

Pure functions only. Expectations follow
``apps/chronicle/docs/person-state-reading.md`` §3.3: only explicitly
reviewed links inside the frozen catalog participate; both sides keep
their own source/phase/Claim attribution; the index can add recorded
reasons but never promotes a previously uncertain source to clear, and
different offices / same-year phases are not auto-conflicts.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import person_state_projection as PP  # noqa: E402
from common import PersistenceError  # noqa: E402

CATALOG_SHA = "a" * 64


def membership(*, fact_refs=None, facts=None) -> dict:
    value = {"catalog_sha": CATALOG_SHA}
    if fact_refs is not None:
        value["fact_refs"] = list(fact_refs)
    if facts is not None:
        value["facts"] = facts
    return value


FACTS = {
    "pf_a": {"source_publication_id": "pub_1", "phase_ids": ["ph_001"], "claim_refs": ["clm_1"]},
    "pf_b": {"source_publication_id": "pub_2", "phase_ids": ["ph_002"], "claim_refs": ["clm_2"]},
    "pf_c": {"source_publication_id": "pub_1", "phase_ids": ["ph_001"], "claim_refs": ["clm_3"]},
}


class DisagreementIndexTests(unittest.TestCase):
    def test_requires_catalog_sha(self) -> None:
        with self.assertRaises(PersistenceError):
            PP.compile_person_state_disagreements([], [], {})

    def test_filters_links_outside_catalog_membership(self) -> None:
        base = [{"topic": "A", "fact_refs": ["pf_a", "pf_b"]}]
        reviewed = [{"topic": "B", "fact_refs": ["pf_c", "pf_missing"]}]
        result = PP.compile_person_state_disagreements(
            base, reviewed, membership(fact_refs=["pf_a", "pf_b", "pf_c"])
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["fact_refs"], ["pf_a", "pf_b"])

    def test_output_is_sorted_and_deterministic(self) -> None:
        base = [
            {"topic": "B", "fact_refs": ["pf_b", "pf_c"]},
            {"topic": "A", "fact_refs": ["pf_a", "pf_b"]},
        ]
        first = PP.compile_person_state_disagreements(base, [], membership())
        second = PP.compile_person_state_disagreements(base, [], membership())
        self.assertEqual(first, second)
        ids = [entry["disagreement_id"] for entry in first]
        self.assertEqual(ids, sorted(ids))

    def test_base_and_reviewed_merge_by_identity_and_union_reasons(self) -> None:
        base = [
            {
                "topic": "same topic",
                "fact_refs": ["pf_a", "pf_b"],
                "reason_codes": ["source_disagreement"],
            }
        ]
        reviewed = [
            {
                "topic": "same topic",
                "fact_refs": ["pf_b", "pf_a"],
                "reason_codes": ["order_unknown"],
            }
        ]
        result = PP.compile_person_state_disagreements(base, reviewed, membership())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["reason_codes"], ["order_unknown", "source_disagreement"])

    def test_both_sides_keep_their_source_phase_and_claim_attribution(self) -> None:
        link = {"topic": "同名事件", "fact_refs": ["pf_a", "pf_b"]}
        result = PP.compile_person_state_disagreements(
            [link], [], membership(facts=FACTS)
        )
        sides = result[0]["sides"]
        self.assertEqual(len(sides), 2)
        publications = [side["source_publication_id"] for side in sides]
        self.assertEqual(publications, ["pub_1", "pub_2"])
        by_pub = {side["source_publication_id"]: side for side in sides}
        self.assertEqual(by_pub["pub_1"]["claim_refs"], ["clm_1"])
        self.assertEqual(by_pub["pub_2"]["claim_refs"], ["clm_2"])
        self.assertEqual(by_pub["pub_1"]["phase_ids"], ["ph_001"])

    def test_single_fact_links_are_not_disagreements(self) -> None:
        result = PP.compile_person_state_disagreements(
            [{"topic": "x", "fact_refs": ["pf_a"]}], [], membership()
        )
        self.assertEqual(result, [])

    def test_unknown_reason_codes_are_dropped_and_default_applied(self) -> None:
        link = {"topic": "x", "fact_refs": ["pf_a", "pf_b"], "reason_codes": ["not_a_code"]}
        result = PP.compile_person_state_disagreements([link], [], membership())
        self.assertEqual(result[0]["reason_codes"], ["source_disagreement"])

    def test_index_does_not_carry_certainty_or_promote(self) -> None:
        link = {
            "topic": "x",
            "fact_refs": ["pf_a", "pf_b"],
            "certainty": "clear",
            "assessment": "supported",
        }
        result = PP.compile_person_state_disagreements([link], [], membership())
        self.assertNotIn("certainty", result[0])
        self.assertNotIn("assessment", result[0])

    def test_explicit_link_requires_two_distinct_facts(self) -> None:
        result = PP.compile_person_state_disagreements(
            [{"topic": "x", "fact_refs": ["pf_a", "pf_a"]}], [], membership()
        )
        self.assertEqual(result, [])

    def test_index_is_bounded_by_the_contract(self) -> None:
        links = [
            {"topic": f"topic-{index}", "fact_refs": ["pf_a", "pf_b"]}
            for index in range(1025)
        ]
        with self.assertRaises(PersistenceError):
            PP.compile_person_state_disagreements(links, [], membership())

    def test_provided_sides_are_preserved_verbatim(self) -> None:
        link = {
            "topic": "x",
            "fact_refs": ["pf_a", "pf_b"],
            "sides": [
                {"source_publication_id": "pub_9", "fact_refs": ["pf_a"], "phase_ids": ["ph_x"]},
                {"source_publication_id": "pub_8", "fact_refs": ["pf_b"], "claim_refs": ["clm_9"]},
            ],
        }
        result = PP.compile_person_state_disagreements([link], [], membership())
        publications = {side["source_publication_id"] for side in result[0]["sides"]}
        self.assertEqual(publications, {"pub_8", "pub_9"})


if __name__ == "__main__":
    unittest.main()
