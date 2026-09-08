"""Deterministic graph and fan-out contracts for the R19 review guard."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import review_subjects as S
from common import PersistenceConflict, canonical_json_bytes, sha256_json
from test_entity_review_conflict_r19_postgres import (
    CANONICAL_A, CANONICAL_B, INCOMING, R19_REFS, review_fixture,
)


def decision(value="same_entity") -> dict:
    return {"decision": value, "confidence": 0.9, "rationale": "人工核对逐字证据"}


def review_plan(fixture: dict) -> dict:
    return {
        subject["left_subject"]["canonical_id"]: S.subject_payload(subject)
        for subject in S.build_review_subjects(
            fixture["initial"], catalog=fixture["catalog"],
            within_book_links=fixture["within_book_links"],
        )
    }


class EntityReviewGraphTests(unittest.TestCase):
    def _validate(self, fixture, plan, proposed, *, prior_status="resolved", proposed_id=CANONICAL_B):
        S.validate_entity_review_decision_graph(
            resolutions=fixture["initial"],
            reviews=[
                (key, "open" if key == proposed_id else prior_status, payload)
                for key, payload in plan.items()
            ],
            proposed_review_id=proposed_id, proposed_payload=proposed,
            catalog=fixture["catalog"], within_book_links=fixture["within_book_links"],
        )

    def test_single_incoming_component_first_link_allowed_second_rejected(self):
        fixture = review_fixture(a_refs=("ent_x",), b_refs=("ent_x",), within=[])
        plan = review_plan(fixture)
        first = copy.deepcopy(plan[CANONICAL_A])
        first["decision"] = decision()
        self._validate(fixture, plan, first, proposed_id=CANONICAL_A, prior_status="open")
        plan[CANONICAL_A] = first
        second = copy.deepcopy(plan[CANONICAL_B])
        second["decision"] = decision()
        before = canonical_json_bytes([fixture, plan, second])
        with self.assertRaises(S.CanonicalIdentityConflict) as caught:
            self._validate(fixture, plan, second)
        self.assertEqual(caught.exception.details["canonical_ids"], [CANONICAL_A, CANONICAL_B])
        self.assertEqual(before, canonical_json_bytes([fixture, plan, second]))

    def test_within_book_bridge_includes_refs_without_cross_source_candidates(self):
        fixture = review_fixture(a_refs=(R19_REFS[0],), b_refs=(R19_REFS[2],))
        plan = review_plan(fixture)
        plan[CANONICAL_A]["decision"] = decision()
        proposed = copy.deepcopy(plan[CANONICAL_B])
        proposed["decision"] = decision()
        with self.assertRaises(S.CanonicalIdentityConflict) as caught:
            self._validate(fixture, plan, proposed)
        self.assertEqual(caught.exception.details["incoming_refs"], [
            {"bundle": INCOMING, "ref": ref} for ref in R19_REFS
        ])

    def _two_group_plan(self):
        fixture = review_fixture(a_refs=("ent_x",), b_refs=("ent_x", "ent_y"), within=[])
        plan = review_plan(fixture)
        plan[CANONICAL_A]["decision"] = decision()
        proposed = copy.deepcopy(plan[CANONICAL_B])
        groups = {group["component_root"]: group for group in proposed["groups"]}
        return fixture, plan, proposed, groups

    def test_batch_default_identifies_only_the_bridging_group(self):
        fixture, plan, proposed, groups = self._two_group_plan()
        proposed["decision"] = decision()
        with self.assertRaises(S.CanonicalIdentityConflict) as caught:
            self._validate(fixture, plan, proposed)
        self.assertEqual(caught.exception.details["review_group_ids"], [groups["ent_x"]["review_group_id"]])
        self.assertEqual(caught.exception.details["proposed_candidate_keys"], [groups["ent_x"]["members"][0]["candidate_key"]])

    def test_same_default_with_non_equivalent_group_override_is_allowed(self):
        for override in ("not_same", "uncertain"):
            with self.subTest(override=override):
                fixture, plan, proposed, groups = self._two_group_plan()
                proposed["decision"] = {
                    **decision(), "group_decisions": [
                        {"review_group_id": groups["ent_x"]["review_group_id"], **decision(override)},
                    ],
                }
                self._validate(fixture, plan, proposed)

    def test_uncertain_default_with_same_override_cannot_bypass_graph_check(self):
        fixture, plan, proposed, groups = self._two_group_plan()
        proposed["decision"] = {
            **decision("uncertain"), "group_decisions": [
                {"review_group_id": groups["ent_x"]["review_group_id"], **decision()},
            ],
        }
        with self.assertRaises(S.CanonicalIdentityConflict):
            self._validate(fixture, plan, proposed)
        proposed["decision"]["group_decisions"][0]["review_group_id"] = groups["ent_y"]["review_group_id"]
        self._validate(fixture, plan, proposed)

    def test_previously_accepted_group_overrides_are_effective(self):
        fixture, plan, proposed, groups = self._two_group_plan()
        prior = plan[CANONICAL_A]
        prior["decision"] = {
            **decision("uncertain"), "group_decisions": [
                {"review_group_id": prior["groups"][0]["review_group_id"], **decision()},
            ],
        }
        proposed["decision"] = decision()
        with self.assertRaises(S.CanonicalIdentityConflict):
            self._validate(fixture, plan, proposed)
        prior["decision"]["decision"] = "same_entity"
        prior["decision"]["group_decisions"][0].update(decision("not_same"))
        self._validate(fixture, plan, proposed)

    def test_unconnected_same_name_components_remain_independently_reviewable(self):
        for within_decision in ("uncertain", "not_same"):
            with self.subTest(within_decision=within_decision):
                fixture = review_fixture(
                    a_refs=("ent_x",), b_refs=("ent_y",),
                    within=[("ent_x", "ent_y", within_decision)],
                )
                plan = review_plan(fixture)
                plan[CANONICAL_A]["decision"] = decision()
                proposed = copy.deepcopy(plan[CANONICAL_B])
                proposed["decision"] = decision()
                self._validate(fixture, plan, proposed)

    def test_open_or_dismissed_payload_decision_is_not_an_equivalence_edge(self):
        fixture = review_fixture()
        plan = review_plan(fixture)
        plan[CANONICAL_A]["decision"] = decision()
        proposed = copy.deepcopy(plan[CANONICAL_B])
        proposed["decision"] = decision()
        for status in ("open", "dismissed"):
            with self.subTest(status=status):
                self._validate(fixture, plan, proposed, prior_status=status)

    def test_frozen_same_links_are_used_until_overridden_by_human_decisions(self):
        fixture = review_fixture()
        for link in fixture["initial"][0]["entity_links"]:
            link["decision"] = "same_entity"
        plan = review_plan(fixture)
        proposed = copy.deepcopy(plan[CANONICAL_B])
        proposed["decision"] = decision()
        with self.assertRaises(S.CanonicalIdentityConflict):
            self._validate(fixture, plan, proposed, prior_status="open")
        plan[CANONICAL_A]["decision"] = decision("uncertain")
        self._validate(fixture, plan, proposed)

    def test_catalog_membership_is_authority_even_when_plan_predates_publication(self):
        fixture = review_fixture()
        plan = review_plan(fixture)
        fixture["catalog"]["canonical_entities"][0]["representations"].append(
            {"bundle": INCOMING, "ref": R19_REFS[0]}
        )
        proposed = copy.deepcopy(plan[CANONICAL_B])
        proposed["decision"] = decision()
        with self.assertRaises(S.CanonicalIdentityConflict):
            self._validate(fixture, plan, proposed, prior_status="open")

    def test_pre_batch_subject_plan_keeps_its_frozen_fanout(self):
        fixture = review_fixture()
        plan = review_plan(fixture)
        for payload in plan.values():
            payload["review_subject_version"] = "0.1"
            payload.pop("groups")
        plan[CANONICAL_A]["decision"] = decision()
        proposed = copy.deepcopy(plan[CANONICAL_B])
        proposed["decision"] = decision()
        with self.assertRaises(S.CanonicalIdentityConflict):
            self._validate(fixture, plan, proposed)

    def test_legacy_candidate_reviews_use_published_membership_without_a_batch(self):
        fixture = review_fixture(a_refs=("ent_x",), b_refs=("ent_x",), within=[])
        reviews = []
        for index, artifact in enumerate(fixture["initial"]):
            member = artifact["entity_links"][0]
            payload = {
                "scope": "resolution", "link_kind": "entity",
                "resolution_sha256": sha256_json(artifact),
                "candidate_id": member["candidate_id"],
                "decision": decision(),
            }
            reviews.append((index, "resolved" if index == 0 else "open", payload))
        with self.assertRaises(S.CanonicalIdentityConflict) as caught:
            S.validate_entity_review_decision_graph(
                resolutions=fixture["initial"], reviews=reviews,
                proposed_review_id=1, proposed_payload=reviews[1][2],
                catalog=fixture["catalog"], within_book_links=None,
            )
        self.assertEqual(caught.exception.details["canonical_ids"], [CANONICAL_A, CANONICAL_B])
        self.assertEqual(caught.exception.details["review_group_ids"], [])

    def test_missing_frozen_candidate_fails_closed(self):
        fixture = review_fixture()
        plan = review_plan(fixture)
        proposed = copy.deepcopy(plan[CANONICAL_B])
        proposed["decision"] = decision()
        fixture["initial"][0]["entity_links"].pop()
        with self.assertRaises(PersistenceConflict):
            self._validate(fixture, plan, proposed)

    def test_event_decisions_do_not_acquire_an_entity_guard(self):
        S.validate_entity_review_decision_graph(
            resolutions=[], reviews=[], proposed_review_id="event-review",
            proposed_payload={"link_kind": "event", "decision": decision("same_occurrence")},
            catalog=None, within_book_links=None,
        )


if __name__ == "__main__":
    unittest.main()
