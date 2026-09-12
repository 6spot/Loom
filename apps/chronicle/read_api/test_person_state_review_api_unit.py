"""Unit tests for the C2-R3-T07 person-state review API dispatch.

These exercise the pure/parsing parts of the mixed queue and the person-state
branch without a database: ``review_scope`` normalization and cursor binding,
the anchor/candidate projections that turn a frozen T06 package into the
readable review DTO, and the decision override translation (``candidate_key``
accepted by the browser -> T06 ``candidate_id``).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
for candidate in (str(HERE), str(PERSISTENCE)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import studio_person_states as person_states  # noqa: E402
import studio_reviews as studio  # noqa: E402


def _candidate(**overrides) -> dict:
    candidate = {
        "candidate_key": "psc_000000000000000000000001",
        "kind": "fact",
        "chapter_id": "ch_001",
        "item_ref": "pf_001",
        "phase_ids": ["ph_001"],
        "anchor_ids": ["anc_1"],
        "source_fact_refs": ["pf_001"],
        "revision_ref": "pf_000001",
        "predicted_effect": "current_identity",
        "dimension": "office",
        "operation": "start",
        "qualification": "ordinary",
        "attribution": "narrator",
        "assessment_default": "uncertain",
        "allowed_assessments": ["supported", "uncertain", "disputed", "rejected"],
    }
    candidate.update(overrides)
    return candidate


def _package(**overrides) -> dict:
    payload = {
        "scope": "person_state",
        "review_mode": "chapter_state_evidence",
        "plan_version": "c2r3-person-state-review-plan-v1",
        "plan_fingerprint": "a" * 64,
        "chapter_id": "ch_001",
        "artifact_sha256": "b" * 64,
        "person_states_sha256": "c" * 64,
        "base_catalog_sha": "d" * 64,
        "candidates": [_candidate()],
        "candidate_count": 1,
        "default_assessment": "uncertain",
        "allowed_assessments": ["supported", "uncertain", "disputed", "rejected"],
        "decision": None,
    }
    payload.update(overrides)
    return payload


class ReviewScopeQueueUnitTests(unittest.TestCase):
    def test_omitted_scope_defaults_to_resolution(self) -> None:
        spec = studio._parse_page({})
        self.assertEqual(spec["review_scope"], "resolution")

    def test_scope_accepts_all_vocabulary(self) -> None:
        for scope in ("resolution", "person_state", "chapter_content", "all"):
            spec = studio._parse_page({"review_scope": [scope]})
            self.assertEqual(spec["review_scope"], scope)

    def test_unknown_scope_is_a_bad_request(self) -> None:
        with self.assertRaises(studio._BadRequest):
            studio._parse_page({"review_scope": ["everything"]})

    def test_link_kind_only_combines_with_resolution(self) -> None:
        studio._parse_page({"link_kind": ["entity"]})
        for scope in ("person_state", "chapter_content", "all"):
            with self.assertRaises(studio._BadRequest):
                studio._parse_page({"review_scope": [scope], "link_kind": ["entity"]})

    def test_cursor_is_bound_to_review_scope(self) -> None:
        cursor = studio._encode_cursor(
            review_scope="person_state",
            status="open",
            job_id=None,
            link_kind=None,
            created_at="2026-01-01T00:00:00+00:00",
            review_id="019535d9-3df7-7000-8000-000000000001",
        )
        spec = studio._parse_page({"review_scope": ["person_state"], "cursor": [cursor]})
        self.assertEqual(spec["cursor"]["review_scope"], "person_state")
        with self.assertRaises(studio._BadRequest):
            studio._parse_page({"review_scope": ["all"], "cursor": [cursor]})

    def test_person_state_summary_is_bounded(self) -> None:
        row = (
            "019535d9-3df7-7000-8000-000000000001", "019535d9-3df7-7000-8000-000000000002",
            None, "stage_gate", "open", _package(
                decision={
                    "default_assessment": "supported",
                    "rationale": "bulk",
                    "overrides": [{"candidate_id": "psc_x", "assessment": "supported", "rationale": "y"}],
                    "decisions": {"psc_x": {"assessment": "supported"}},
                }
            ),
            "2026-01-01T00:00:00+00:00", None, "needs_review",
            "019535d9-3df7-7000-8000-000000000003",
            "019535d9-3df7-7000-8000-000000000004", "周瑜傳", 1, "zhouyu.md",
            "e" * 64, "lzh", "test",
        )
        class _Conn:
            def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
                class _Cursor:
                    def fetchone(self):
                        return None

                return _Cursor()

        item = studio._summary(row, _Conn(), plan_fingerprint="envelope")
        self.assertEqual(item["scope"], "person_state")
        self.assertEqual(item["candidate_count"], 1)
        self.assertEqual(item["plan_fingerprint"], "a" * 64)
        self.assertEqual(item["left_label"], "阶段依据审核")
        self.assertEqual(item["decision"]["override_count"], 1)
        # The per-candidate decision map is never inlined into the queue page.
        self.assertNotIn("decisions", item["decision"])
        self.assertNotIn("candidates", item)


class PersonStateProjectionUnitTests(unittest.TestCase):
    def test_fact_projects_person_value_and_quote(self) -> None:
        item = {
            "person_ref": {"kind": "entity", "ref": "ent_001"},
            "dimension": "office",
            "value_ref": {"kind": "entity", "ref": "ent_002"},
            "relation": None,
            "target_ref": None,
            "operation": "start",
            "qualification": "ordinary",
            "phase_ref": "ph_001",
            "attribution": "narrator",
            "reason_codes": ["tenure_unproven"],
        }
        projected = person_states._candidate_projection(
            _candidate(),
            item=item,
            entities={"ent_001": "周瑜", "ent_002": "建威中郎將"},
            anchors={"anc_1": {"quote": "瑜為建威中郎將"}},
            source_label="周瑜傳",
        )
        self.assertEqual(projected["person_name"], "周瑜")
        self.assertEqual(projected["value"], "建威中郎將")
        self.assertEqual(projected["quote"], "瑜為建威中郎將")
        self.assertEqual(projected["source_label"], "周瑜傳")
        self.assertEqual(projected["phase_refs"], ["ph_001"])
        self.assertEqual(projected["reason_codes"], ["tenure_unproven"])

    def test_affiliation_projects_relation_and_target(self) -> None:
        candidate = _candidate(dimension="affiliation", relation=None)
        item = {
            "person_ref": {"kind": "entity", "ref": "ent_001"},
            "dimension": "affiliation",
            "value_ref": None,
            "relation": "serves",
            "target_ref": {"kind": "entity", "ref": "ent_003"},
            "operation": "start",
            "qualification": "ordinary",
            "phase_ref": "ph_001",
            "attribution": "narrator",
        }
        projected = person_states._candidate_projection(
            candidate,
            item=item,
            entities={"ent_001": "周瑜", "ent_003": "孫策"},
            anchors={},
            source_label=None,
        )
        self.assertEqual(projected["value"], "serves")
        self.assertEqual(projected["target"], "孫策")
        self.assertEqual(projected["relation"], "serves")

    def test_phase_and_disagreement_project_readable_values(self) -> None:
        phase = person_states._candidate_projection(
            _candidate(kind="phase", item_ref="ph_001"),
            item={"phase_id": "ph_001", "label": "初"},
            entities={},
            anchors={},
            source_label=None,
        )
        self.assertEqual(phase["value"], "初")
        disagreement = person_states._candidate_projection(
            _candidate(kind="disagreement", item_ref="pd_001"),
            item={"topic": "任職_月份", "phase_refs": ["ph_001", "ph_002"]},
            entities={},
            anchors={},
            source_label=None,
        )
        self.assertEqual(disagreement["value"], "任職_月份")

    def test_package_anchors_are_deduped_and_candidate_scoped(self) -> None:
        payload = _package(
            candidates=[
                _candidate(candidate_key="psc_a", anchor_ids=["anc_2", "anc_1"]),
                _candidate(candidate_key="psc_b", anchor_ids=["anc_1"], kind="phase"),
            ]
        )
        self.assertEqual(person_states._package_anchor_ids(payload), ["anc_1", "anc_2"])
        self.assertEqual(
            person_states._package_anchor_ids(payload, candidate_id="psc_b"), ["anc_1"]
        )
        with self.assertRaises(person_states.PersonStateNotFound):
            person_states._package_anchor_ids(payload, candidate_id="psc_missing")

    def test_candidate_cursor_is_plan_bound(self) -> None:
        cursor = person_states.encode_candidate_cursor(
            review_id="019535d9-3df7-7000-8000-000000000001",
            plan_fingerprint="a" * 64,
            offset=3,
        )
        self.assertEqual(
            person_states.decode_candidate_cursor(
                cursor,
                review_id="019535d9-3df7-7000-8000-000000000001",
                plan_fingerprint="a" * 64,
            ),
            3,
        )
        with self.assertRaises(person_states.PersonStateBadRequest):
            person_states.decode_candidate_cursor(
                cursor,
                review_id="019535d9-3df7-7000-8000-000000000001",
                plan_fingerprint="b" * 64,
            )
        with self.assertRaises(person_states.PersonStateBadRequest):
            person_states.decode_candidate_cursor(
                "bogus",
                review_id="019535d9-3df7-7000-8000-000000000001",
                plan_fingerprint="a" * 64,
            )

    def test_override_translation_accepts_candidate_key_or_id(self) -> None:
        normalized = person_states._normalize_overrides(
            [
                {"candidate_key": "psc_a", "assessment": "supported", "rationale": "x"},
                {"candidate_id": "psc_b", "assessment": "uncertain", "rationale": "y"},
            ]
        )
        self.assertEqual(
            [entry["candidate_id"] for entry in normalized], ["psc_a", "psc_b"]
        )
        with self.assertRaises(person_states.PersonStateBadRequest):
            person_states._normalize_overrides([{"assessment": "supported"}])
        with self.assertRaises(person_states.PersonStateBadRequest):
            person_states._normalize_overrides("not-a-list")

    def test_evidence_kind_follows_real_claim_and_record_source(self) -> None:
        # A fact that actually carries claim_refs is direct_claim evidence.
        self.assertEqual(
            person_states._candidate_evidence_kind(
                _candidate(kind="fact"), {"claim_refs": ["clm_001"]}
            ),
            "direct_claim",
        )
        # A fact with only exact source_selections (no direct Claim) must not
        # be reported as Claim evidence.
        self.assertEqual(
            person_states._candidate_evidence_kind(
                _candidate(kind="fact"), {"claim_refs": []}
            ),
            "record_source",
        )
        self.assertEqual(
            person_states._candidate_evidence_kind(_candidate(kind="fact"), {}),
            "record_source",
        )
        self.assertEqual(
            person_states._candidate_evidence_kind(_candidate(kind="phase"), {}),
            "record_source",
        )

    def test_shared_anchor_keeps_every_candidate_key(self) -> None:
        candidate_a = _candidate(candidate_key="psc_a", anchor_ids=["anc_1"])
        candidate_b = _candidate(
            candidate_key="psc_b", anchor_ids=["anc_1"], kind="fact", item_ref="pf_002"
        )
        descriptor = person_states._anchor_descriptor(
            review_id="019535d9-3df7-7000-8000-000000000001",
            anchor_id="anc_1",
            anchor={"anchor_id": "anc_1", "chapter_id": "ch_001", "start": 0, "end": 3},
            chapter_info={},
            artifact=None,
            candidates=[candidate_a, candidate_b],
            state_index={},
        )
        self.assertEqual(descriptor["candidate_keys"], ["psc_a", "psc_b"])
        self.assertEqual(descriptor["evidence_kinds"], ["record_source"])


if __name__ == "__main__":
    unittest.main()
