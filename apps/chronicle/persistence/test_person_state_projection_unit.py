"""Unit tests for the Chronicle C2-R3-T04 person-state projection compiler.

Pure functions only (no PostgreSQL / network / model). Expectations are
derived from ``apps/chronicle/docs/person-state-reading.md`` sections
2-4 and the D01 real/synthetic counterexample intents, not from the
implementation's internals: the decision table fixes which inputs are
current / clear, which are ``uncertain`` and with which reason code.
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

PERSON = "ent_002"
PERSON_ID = "0192f0a0-0000-7000-8000-00000000cc07"
CHAPTER_ID = "ch_756922e9af0d759d29d7475f"
REVISION_ID = "rev_c2r3_demo_001"
PUBLICATION_ID = "0192f0a0-0000-7000-8000-00000000bb02"

ALL_PHASES = ["ph_001", "ph_002", "ph_003"]


def order(assertion_id: str, earlier: str, later: str) -> dict:
    return {
        "assertion_id": assertion_id,
        "earlier_phase_ref": earlier,
        "later_phase_ref": later,
    }


CHAIN = [order("po_01", "ph_001", "ph_002"), order("po_02", "ph_002", "ph_003")]
CHAIN_ASSESSMENTS = {"po_01": "supported", "po_02": "supported"}


def fact(
    fact_ref: str,
    *,
    phase_ref: str = "ph_002",
    dimension: str = "office",
    value: str | None = "建威中郎將",
    relation: str | None = None,
    target: str | None = None,
    target_ref: str | None = None,
    operation: str = "start",
    qualification: str = "ordinary",
    attribution: str = "narrator",
) -> dict:
    return {
        "fact_ref": fact_ref,
        "person_ref": {"kind": "entity", "ref": PERSON},
        "person_key": PERSON,
        "dimension": dimension,
        "value": value,
        "value_ref": None,
        "relation": relation,
        "target": target,
        "target_ref": target_ref,
        "operation": operation,
        "qualification": qualification,
        "phase_ref": phase_ref,
        "claim_refs": [],
        "anchor_ids": ["anc_" + "1" * 16],
        "attribution": attribution,
        "chapter_id": CHAPTER_ID,
        "revision_id": REVISION_ID,
        "chapter_publication_id": PUBLICATION_ID,
    }


def build(
    facts: list[dict],
    *,
    phase_orders: list[dict] | None = None,
    continuities: list[dict] | None = None,
    disagreements: list[dict] | None = None,
    phases: list[str] | None = None,
) -> dict:
    seen = set(phases or ALL_PHASES)
    for entry in facts:
        seen.add(entry["phase_ref"])
    return {
        "phases": [{"phase_id": pid} for pid in sorted(seen)],
        "phase_orders": list(phase_orders or []),
        "unit_phases": [],
        "facts": list(facts),
        "continuities": list(continuities or []),
        "disagreements": list(disagreements or []),
    }


def compile_(
    evidence: dict,
    assessments: dict,
    *,
    canonical_map: dict | None = None,
    manifest: dict | None = None,
):
    return PP.compile_person_state_projection(
        evidence,
        assessments,
        canonical_map if canonical_map is not None else {PERSON: PERSON_ID},
        manifest if manifest is not None else {"current_phase_id": "ph_002"},
    )


def item_for(result: dict, fact_ref: str) -> dict:
    for entry in result["items"]:
        if fact_ref in [source["fact_ref"] for source in entry["source_facts"]]:
            return entry
    raise AssertionError(f"no item for {fact_ref}")


class DecisionTableTests(unittest.TestCase):
    def test_supported_current_phase_is_clear(self) -> None:
        evidence = build([fact("pf_001", phase_ref="ph_002")], phase_orders=CHAIN)
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported"})
        item = item_for(result, "pf_001")
        self.assertEqual(item["certainty"], "clear")
        self.assertEqual(item["reason_codes"], [])
        self.assertTrue(item["current"])

    def test_prior_without_continuity_is_tenure_unproven(self) -> None:
        evidence = build([fact("pf_001", phase_ref="ph_001")], phase_orders=CHAIN)
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported"})
        item = item_for(result, "pf_001")
        self.assertEqual(item["certainty"], "uncertain")
        self.assertEqual(item["reason_codes"], ["tenure_unproven"])
        self.assertFalse(item["current"])

    def test_proven_continuity_covers_current_phase(self) -> None:
        continuity = {
            "assertion_id": "pc_01",
            "fact_ref": "pf_001",
            "start_phase_ref": "ph_001",
            "end_phase_ref": None,
        }
        evidence = build(
            [fact("pf_001", phase_ref="ph_001")], phase_orders=CHAIN, continuities=[continuity]
        )
        result = compile_(
            evidence,
            {**CHAIN_ASSESSMENTS, "pf_001": "supported", "pc_01": "supported"},
        )
        item = item_for(result, "pf_001")
        self.assertEqual(item["certainty"], "clear")
        self.assertTrue(item["current"])

    def test_unassessed_continuity_does_not_cover(self) -> None:
        continuity = {
            "assertion_id": "pc_01",
            "fact_ref": "pf_001",
            "start_phase_ref": "ph_001",
            "end_phase_ref": None,
        }
        evidence = build(
            [fact("pf_001", phase_ref="ph_001")], phase_orders=CHAIN, continuities=[continuity]
        )
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported"})
        self.assertIn("tenure_unproven", item_for(result, "pf_001")["reason_codes"])

    def test_future_phase_is_not_leaked(self) -> None:
        evidence = build([fact("pf_003", phase_ref="ph_003")], phase_orders=CHAIN)
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_003": "supported"})
        self.assertEqual(result["items"], [])
        self.assertEqual(result["changes"], [])
        self.assertTrue(any(d["code"] == "phase_not_reached" for d in result["diagnostics"]))

    def test_unknown_order_does_not_carry_previous(self) -> None:
        evidence = build([fact("pf_001", phase_ref="ph_001")])  # no proven edge
        result = compile_(evidence, {"pf_001": "supported"})
        item = item_for(result, "pf_001")
        self.assertEqual(item["reason_codes"], ["order_unknown"])
        self.assertFalse(item["current"])

    def test_rejected_fact_is_excluded(self) -> None:
        evidence = build([fact("pf_001", phase_ref="ph_002")], phase_orders=CHAIN)
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_001": "rejected"})
        self.assertEqual(result["items"], [])
        self.assertTrue(any(d["code"] == "rejected" for d in result["diagnostics"]))

    def test_missing_assessment_is_evidence_uncertain(self) -> None:
        evidence = build([fact("pf_001", phase_ref="ph_002")], phase_orders=CHAIN)
        result = compile_(evidence, dict(CHAIN_ASSESSMENTS))
        item = item_for(result, "pf_001")
        self.assertEqual(item["reason_codes"], ["evidence_uncertain"])
        self.assertFalse(item["current"])

    def test_disputed_fact_is_source_disagreement(self) -> None:
        evidence = build([fact("pf_001", phase_ref="ph_002")], phase_orders=CHAIN)
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_001": "disputed"})
        item = item_for(result, "pf_001")
        self.assertEqual(item["reason_codes"], ["source_disagreement"])
        self.assertFalse(item["current"])

    def test_applicable_disagreement_adds_reason_without_promotion(self) -> None:
        evidence = build(
            [fact("pf_001", phase_ref="ph_002")],
            phase_orders=CHAIN,
            disagreements=[{"assertion_id": "pd_01", "topic": "同名事件", "fact_refs": ["pf_001"]}],
        )
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported"})
        item = item_for(result, "pf_001")
        self.assertEqual(item["certainty"], "uncertain")
        self.assertIn("source_disagreement", item["reason_codes"])

    def test_unknown_person_is_diagnosed(self) -> None:
        evidence = build([fact("pf_001", phase_ref="ph_002")], phase_orders=CHAIN)
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported"}, canonical_map={})
        self.assertEqual(result["items"], [])
        self.assertTrue(any(d["code"] == "unknown_person" for d in result["diagnostics"]))


class QualificationTests(unittest.TestCase):
    def test_recommendation_never_enters_current_identity(self) -> None:
        evidence = build(
            [fact("pf_rec", phase_ref="ph_002", qualification="recommendation", operation="attest")],
            phase_orders=CHAIN,
        )
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_rec": "supported"})
        item = item_for(result, "pf_rec")
        self.assertEqual(item["certainty"], "uncertain")
        self.assertIn("attribution_uncertain", item["reason_codes"])
        self.assertFalse(item["current"])

    def test_posthumous_never_enters_current_identity(self) -> None:
        evidence = build(
            [fact("pf_po", phase_ref="ph_002", qualification="posthumous", operation="attest")],
            phase_orders=CHAIN,
        )
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_po": "supported"})
        item = item_for(result, "pf_po")
        self.assertFalse(item["current"])
        self.assertIn("attribution_uncertain", item["reason_codes"])

    def test_self_designation_keeps_its_qualifier(self) -> None:
        evidence = build(
            [fact("pf_self", phase_ref="ph_002", qualification="self_designation", operation="attest")],
            phase_orders=CHAIN,
        )
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_self": "supported"})
        item = item_for(result, "pf_self")
        self.assertFalse(item["current"])
        self.assertEqual(item["qualification"], "self_designation")
        self.assertIn("attribution_uncertain", item["reason_codes"])

    def test_quotation_is_not_current(self) -> None:
        evidence = build(
            [fact("pf_q", phase_ref="ph_002", attribution="quotation", operation="attest")],
            phase_orders=CHAIN,
        )
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_q": "supported"})
        item = item_for(result, "pf_q")
        self.assertFalse(item["current"])
        self.assertIn("attribution_uncertain", item["reason_codes"])

    def test_annotation_stays_current_but_uncertain(self) -> None:
        evidence = build(
            [fact("pf_a", phase_ref="ph_002", attribution="annotation", operation="attest")],
            phase_orders=CHAIN,
        )
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_a": "supported"})
        item = item_for(result, "pf_a")
        self.assertTrue(item["current"])
        self.assertEqual(item["certainty"], "uncertain")
        self.assertIn("attribution_uncertain", item["reason_codes"])


class PhaseModeTests(unittest.TestCase):
    def test_process_mode_shows_every_stage_and_not_only_the_last(self) -> None:
        evidence = build(
            [
                fact("pf_01", phase_ref="ph_001", value="建威中郎將"),
                fact("pf_02", phase_ref="ph_002", value="偏將軍"),
            ],
            phase_orders=CHAIN,
        )
        manifest = {
            "unit_phase": {"mode": "process", "phase_ids": ["ph_001", "ph_002"]},
            "current_phase_id": "ph_002",
        }
        result = compile_(
            evidence,
            {**CHAIN_ASSESSMENTS, "pf_01": "supported", "pf_02": "supported"},
            manifest=manifest,
        )
        current = {entry["value"] for entry in result["items"] if entry["current"]}
        self.assertEqual(current, {"建威中郎將", "偏將軍"})

    def test_unknown_mode_does_not_carry_a_previous_phase(self) -> None:
        evidence = build([fact("pf_01", phase_ref="ph_002")], phase_orders=CHAIN)
        manifest = {
            "unit_phase": {"mode": "unknown", "phase_ids": ["ph_002"]},
            "current_phase_id": "ph_002",
        }
        result = compile_(
            evidence, {**CHAIN_ASSESSMENTS, "pf_01": "supported"}, manifest=manifest
        )
        item = item_for(result, "pf_01")
        self.assertFalse(item["current"])
        self.assertIn("order_unknown", item["reason_codes"])

    def test_ambiguous_mode_presents_material_without_a_unity(self) -> None:
        evidence = build([fact("pf_01", phase_ref="ph_001")], phase_orders=CHAIN)
        manifest = {
            "unit_phase": {"mode": "ambiguous", "phase_ids": ["ph_001", "ph_002"]},
            "current_phase_id": "ph_001",
        }
        result = compile_(
            evidence, {**CHAIN_ASSESSMENTS, "pf_01": "supported"}, manifest=manifest
        )
        item = item_for(result, "pf_01")
        self.assertFalse(item["current"])
        self.assertIn("order_unknown", item["reason_codes"])

    def test_rerun_of_same_unit_is_identical(self) -> None:
        evidence = build([fact("pf_01", phase_ref="ph_002")], phase_orders=CHAIN)
        manifest = {"unit_phase": {"mode": "single", "phase_ids": ["ph_002"]}}
        first = compile_(evidence, {"pf_01": "supported"}, manifest=manifest)
        second = compile_(evidence, {"pf_01": "supported"}, manifest=manifest)
        self.assertEqual(first, second)


class EndAndReappointmentTests(unittest.TestCase):
    def test_targeted_end_closes_only_the_same_key(self) -> None:
        evidence = build(
            [
                fact("pf_a", phase_ref="ph_001", value="建威中郎將"),
                fact("pf_b", phase_ref="ph_001", value="偏將軍"),
                fact("pf_end_a", phase_ref="ph_002", value="建威中郎將", operation="end"),
            ],
            phase_orders=CHAIN,
        )
        result = compile_(
            evidence,
            {
                **CHAIN_ASSESSMENTS,
                "pf_a": "supported",
                "pf_b": "supported",
                "pf_end_a": "supported",
            },
        )
        item_a = item_for(result, "pf_a")
        item_b = item_for(result, "pf_b")
        self.assertTrue(item_a["ended"])
        self.assertFalse(item_a["current"])
        self.assertFalse(item_b["ended"])
        ends = [c for c in result["changes"] if c["operation"] == "end"]
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0]["from_phase_id"], "ph_001")

    def test_proven_end_after_current_keeps_the_tenure_current(self) -> None:
        evidence = build(
            [
                fact("pf_a", phase_ref="ph_001", value="建威中郎將"),
                fact("pf_end_a", phase_ref="ph_003", value="建威中郎將", operation="end"),
            ],
            phase_orders=CHAIN,
        )
        result = compile_(
            evidence,
            {**CHAIN_ASSESSMENTS, "pf_a": "supported", "pf_end_a": "supported"},
        )
        item = item_for(result, "pf_a")
        self.assertTrue(item["current"])
        self.assertEqual(item["certainty"], "clear")

    def test_reappointment_after_end_forms_a_new_current_tenure(self) -> None:
        evidence = build(
            [
                fact("pf_a1", phase_ref="ph_001", value="偏將軍"),
                fact("pf_end_a", phase_ref="ph_002", value="偏將軍", operation="end"),
                fact("pf_a2", phase_ref="ph_003", value="偏將軍"),
            ],
            phase_orders=CHAIN,
        )
        manifest = {"current_phase_id": "ph_003"}
        result = compile_(
            evidence,
            {
                **CHAIN_ASSESSMENTS,
                "pf_a1": "supported",
                "pf_end_a": "supported",
                "pf_a2": "supported",
            },
            manifest=manifest,
        )
        old = item_for(result, "pf_a1")
        new = item_for(result, "pf_a2")
        self.assertFalse(old["current"])
        self.assertTrue(old["ended"])
        self.assertTrue(new["current"])
        self.assertEqual(new["certainty"], "clear")

    def test_concurrent_offices_coexist(self) -> None:
        evidence = build(
            [
                fact("pf_01", phase_ref="ph_002", value="偏將軍"),
                fact("pf_02", phase_ref="ph_002", value="南郡太守"),
            ],
            phase_orders=CHAIN,
        )
        result = compile_(
            evidence,
            {**CHAIN_ASSESSMENTS, "pf_01": "supported", "pf_02": "supported"},
        )
        current_values = {entry["value"] for entry in result["items"] if entry["current"]}
        self.assertEqual(current_values, {"偏將軍", "南郡太守"})

    def test_reported_end_does_not_close_a_narrated_tenure(self) -> None:
        evidence = build(
            [
                fact("pf_a", phase_ref="ph_001", value="左將軍"),
                fact(
                    "pf_end_a",
                    phase_ref="ph_002",
                    value="左將軍",
                    operation="end",
                    qualification="reported",
                ),
            ],
            phase_orders=CHAIN,
        )
        result = compile_(
            evidence,
            {**CHAIN_ASSESSMENTS, "pf_a": "supported", "pf_end_a": "supported"},
        )
        item = item_for(result, "pf_a")
        self.assertFalse(item["ended"])
        self.assertEqual(item["reason_codes"], ["tenure_unproven"])
        end = [c for c in result["changes"] if c["operation"] == "end"][0]
        self.assertIn("attribution_uncertain", end["reason_codes"])

    def test_affiliation_end_only_affects_its_relation_target(self) -> None:
        evidence = build(
            [
                fact(
                    "pf_serve",
                    phase_ref="ph_001",
                    dimension="affiliation",
                    value=None,
                    relation="serves",
                    target="田楷",
                    target_ref="ent_tian",
                ),
                fact(
                    "pf_attach",
                    phase_ref="ph_001",
                    dimension="affiliation",
                    value=None,
                    relation="attached_to",
                    target="陶謙",
                    target_ref="ent_tao",
                ),
                fact(
                    "pf_end_serve",
                    phase_ref="ph_002",
                    dimension="affiliation",
                    value=None,
                    relation="serves",
                    target="田楷",
                    target_ref="ent_tian",
                    operation="end",
                ),
            ],
            phase_orders=CHAIN,
        )
        result = compile_(
            evidence,
            {
                **CHAIN_ASSESSMENTS,
                "pf_serve": "supported",
                "pf_attach": "supported",
                "pf_end_serve": "supported",
            },
        )
        self.assertTrue(item_for(result, "pf_serve")["ended"])
        self.assertFalse(item_for(result, "pf_attach")["ended"])


class IntegrationShapeTests(unittest.TestCase):
    def test_value_ref_resolves_display_label_and_canonical_id(self) -> None:
        entry = fact("pf_01", phase_ref="ph_002", value=None)
        entry["value_ref"] = {"kind": "entity", "ref": "ent_office"}
        evidence = build([entry], phase_orders=CHAIN)
        result = compile_(
            evidence,
            {**CHAIN_ASSESSMENTS, "pf_01": "supported"},
            canonical_map={
                PERSON: PERSON_ID,
                "ent_office": "office-uuid",
                "labels": {"ent_office": "偏將軍"},
            },
        )
        item = item_for(result, "pf_01")
        self.assertEqual(item["value"], "偏將軍")
        self.assertEqual(item["value_id"], "office-uuid")

    def test_nested_person_states_and_origin_provenance_are_accepted(self) -> None:
        entry = fact("pf_01", phase_ref="ph_002")
        entry.pop("chapter_id")
        entry.pop("revision_id")
        entry.pop("chapter_publication_id")
        entry.pop("anchor_ids")
        entry["origin"] = {
            "chapter_id": CHAPTER_ID,
            "origin_revision_id": REVISION_ID,
            "anchor_ids": ["anc_" + "2" * 16],
        }
        inner = build([entry], phase_orders=CHAIN)
        result = compile_(
            {"person_states": inner},
            {**CHAIN_ASSESSMENTS, "pf_01": "supported"},
        )
        source = result["items"][0]["source_facts"][0]
        self.assertEqual(source["chapter_id"], CHAPTER_ID)
        self.assertEqual(source["revision_id"], REVISION_ID)
        self.assertEqual(source["anchor_ids"], ["anc_" + "2" * 16])
        self.assertEqual(result["items"][0]["evidence_count"], 1)

    def test_assembled_fact_id_shape_is_accepted(self) -> None:
        entry = fact("pf_001", phase_ref="ph_002")
        entry["fact_id"] = entry.pop("fact_ref")
        entry["origin"] = {"chapter_id": CHAPTER_ID, "origin_revision_id": REVISION_ID}
        evidence = build([entry], phase_orders=CHAIN)
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported"})
        item = item_for(result, "pf_001")
        self.assertTrue(item["current"])

    def test_reading_manifest_entity_labels_resolve_display(self) -> None:
        entry = fact("pf_01", phase_ref="ph_002", value=None)
        entry["value_ref"] = {"kind": "entity", "ref": "ent_office"}
        evidence = build([entry], phase_orders=CHAIN)
        result = compile_(
            evidence,
            {**CHAIN_ASSESSMENTS, "pf_01": "supported"},
            manifest={"current_phase_id": "ph_002", "entity_labels": {"ent_office": "偏將軍"}},
        )
        self.assertEqual(item_for(result, "pf_01")["value"], "偏將軍")


class DeterminismAndBoundsTests(unittest.TestCase):
    def test_projection_hash_is_stable_for_identical_input(self) -> None:
        evidence = build(
            [
                fact("pf_01", phase_ref="ph_001", value="建威中郎將"),
                fact("pf_02", phase_ref="ph_002", value="偏將軍"),
            ],
            phase_orders=CHAIN,
        )
        assessments = {**CHAIN_ASSESSMENTS, "pf_01": "supported", "pf_02": "supported"}
        first = compile_(evidence, assessments)
        second = compile_(evidence, assessments)
        self.assertEqual(first, second)
        self.assertEqual(first["projection_sha256"], second["projection_sha256"])

    def test_item_ids_are_stable_and_keyed_by_fact(self) -> None:
        evidence = build([fact("pf_01", phase_ref="ph_002")], phase_orders=CHAIN)
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_01": "supported"})
        again = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_01": "supported"})
        self.assertEqual(item_for(result, "pf_01")["item_id"], item_for(again, "pf_01")["item_id"])

    def test_phase_cycle_fails_closed(self) -> None:
        evidence = build(
            [fact("pf_01", phase_ref="ph_002")],
            phase_orders=CHAIN
            + [order("po_03", "ph_003", "ph_001")],
        )
        with self.assertRaises(PersistenceError):
            compile_(evidence, {**CHAIN_ASSESSMENTS, "po_03": "supported", "pf_01": "supported"})

    def test_fact_bound_rejects_oversized_input(self) -> None:
        facts = [fact(f"pf_{i:04d}", phase_ref="ph_002") for i in range(513)]
        evidence = build(facts, phase_orders=CHAIN)
        with self.assertRaises(PersistenceError):
            compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_0000": "supported"})

    def test_no_material_produces_an_empty_projection(self) -> None:
        evidence = build([], phase_orders=CHAIN, phases=ALL_PHASES)
        result = compile_(evidence, dict(CHAIN_ASSESSMENTS))
        self.assertEqual(result["people"], {})
        self.assertEqual(result["items"], [])
        self.assertEqual(result["counts"]["people"], 0)


if __name__ == "__main__":
    unittest.main()
