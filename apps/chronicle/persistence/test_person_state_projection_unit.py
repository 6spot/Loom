"""Unit tests for the Chronicle C2-R3-T04 person-state projection compiler.

Pure functions only (no PostgreSQL / network / model). Expectations are
derived from ``apps/chronicle/docs/person-state-reading.md`` sections
2-4, the D01 real/synthetic counterexample intents and the T01 shared
DTO contract, not from the implementation's internals: the decision table
fixes which inputs are current / clear, which are ``uncertain`` and with
which reason code, and the emitted items must validate as the frozen T01
``state_item`` DTO.

The fixture values are intentionally contract-conforming (``ch_`` +
24 hex, ``pf_``/``ph_`` numeric refs, 16-hex anchors) so the T01 DTO
validator can be run directly on the compiled output.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import assembly as A  # noqa: E402
import person_state_contract as P  # noqa: E402
import person_state_projection as PP  # noqa: E402
import reading_contract as RC  # noqa: E402
import reading_projection as RP  # noqa: E402
from common import PersistenceError  # noqa: E402

PERSON = "ent_002"
PERSON_ID = "0192f0a0-0000-7000-8000-00000000cc07"
CHAPTER_ID = "ch_756922e9af0d759d29d7475f"
REVISION_ID = "rev_c2r3_demo_001"
PUBLICATION_ID = "0192f0a0-0000-7000-8000-00000000bb02"
SOURCE_TITLE = "周瑜傳"

ALL_PHASES = ["ph_001", "ph_002", "ph_003"]


def anchor(anchor_id: str, quote: str = "建安三年，策授瑜建威中郎將。") -> dict:
    import hashlib

    return {
        "anchor_id": anchor_id,
        "quote": quote,
        "quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
        "revision_id": REVISION_ID,
        "chapter_id": CHAPTER_ID,
    }


ANCHOR = anchor("anc_" + "1" * 16)


def order(assertion_id: str, earlier: str, later: str) -> dict:
    return {
        "assertion_id": assertion_id,
        "earlier_phase_ref": earlier,
        "later_phase_ref": later,
    }


CHAIN = [order("po_001", "ph_001", "ph_002"), order("po_002", "ph_002", "ph_003")]
CHAIN_ASSESSMENTS = {"po_001": "supported", "po_002": "supported"}


def fact(
    fact_ref: str,
    *,
    phase_ref: str = "ph_002",
    dimension: str = "office",
    value: str | None = "建威中郎將",
    value_ref: dict | None = None,
    relation: str | None = None,
    target: str | None = None,
    target_ref: dict | None = None,
    operation: str = "start",
    qualification: str = "ordinary",
    attribution: str = "narrator",
    claim_refs: list[str] | None = None,
    anchors: list[dict] | None = None,
) -> dict:
    resolved_anchors = list(anchors) if anchors is not None else [ANCHOR]
    return {
        "fact_ref": fact_ref,
        "person_ref": {"kind": "entity", "ref": PERSON},
        "person_key": PERSON,
        "dimension": dimension,
        "value": value,
        "value_ref": value_ref,
        "relation": relation,
        "target": target,
        "target_ref": target_ref,
        "operation": operation,
        "qualification": qualification,
        "phase_ref": phase_ref,
        "claim_refs": list(claim_refs or []),
        "anchor_ids": [entry["anchor_id"] for entry in resolved_anchors],
        "anchors": resolved_anchors,
        "attribution": attribution,
        "chapter_id": CHAPTER_ID,
        "revision_id": REVISION_ID,
        "chapter_publication_id": PUBLICATION_ID,
        "source_title": SOURCE_TITLE,
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


def manifest(current: str = "ph_002", **extra: object) -> dict:
    base = {
        "current_phase_id": current,
        "chapter_publications": {CHAPTER_ID: PUBLICATION_ID},
        "chapter_titles": {CHAPTER_ID: SOURCE_TITLE},
    }
    base.update(extra)
    return base


def compile_(
    evidence: dict,
    assessments: dict,
    *,
    canonical_map: dict | None = None,
    reading_manifest: dict | None = None,
):
    return PP.compile_person_state_projection(
        evidence,
        assessments,
        canonical_map if canonical_map is not None else {PERSON: PERSON_ID},
        reading_manifest if reading_manifest is not None else manifest(),
    )


def item_for(result: dict, fact_ref: str) -> dict:
    for entry in result["items"]:
        if fact_ref in [source["fact_ref"] for source in entry["source_facts"]]:
            return entry
    raise AssertionError(f"no item for {fact_ref}")


def assert_dto(test: unittest.TestCase, name: str, value: object) -> None:
    errors = P.validate_person_state_dto(name, value)
    test.assertEqual(errors, [], f"{name} rejected: {errors}")


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
            "assertion_id": "pc_001",
            "fact_ref": "pf_001",
            "start_phase_ref": "ph_001",
            "end_phase_ref": None,
        }
        evidence = build(
            [fact("pf_001", phase_ref="ph_001")], phase_orders=CHAIN, continuities=[continuity]
        )
        result = compile_(
            evidence,
            {**CHAIN_ASSESSMENTS, "pf_001": "supported", "pc_001": "supported"},
        )
        item = item_for(result, "pf_001")
        self.assertEqual(item["certainty"], "clear")
        self.assertTrue(item["current"])

    def test_unassessed_continuity_does_not_cover(self) -> None:
        continuity = {
            "assertion_id": "pc_001",
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
            disagreements=[{"assertion_id": "pd_001", "topic": "同名事件", "fact_refs": ["pf_001"]}],
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
            [fact("pf_001", phase_ref="ph_002", qualification="recommendation", operation="attest")],
            phase_orders=CHAIN,
        )
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported"})
        item = item_for(result, "pf_001")
        self.assertEqual(item["certainty"], "uncertain")
        self.assertIn("attribution_uncertain", item["reason_codes"])
        self.assertFalse(item["current"])

    def test_posthumous_never_enters_current_identity(self) -> None:
        evidence = build(
            [fact("pf_001", phase_ref="ph_002", qualification="posthumous", operation="attest")],
            phase_orders=CHAIN,
        )
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported"})
        item = item_for(result, "pf_001")
        self.assertFalse(item["current"])
        self.assertIn("attribution_uncertain", item["reason_codes"])

    def test_self_designation_keeps_its_qualifier(self) -> None:
        evidence = build(
            [fact("pf_001", phase_ref="ph_002", qualification="self_designation", operation="attest")],
            phase_orders=CHAIN,
        )
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported"})
        item = item_for(result, "pf_001")
        self.assertFalse(item["current"])
        self.assertEqual(item["qualification"], "self_designation")
        self.assertIn("attribution_uncertain", item["reason_codes"])

    def test_quotation_is_not_current(self) -> None:
        evidence = build(
            [fact("pf_001", phase_ref="ph_002", attribution="quotation", operation="attest")],
            phase_orders=CHAIN,
        )
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported"})
        item = item_for(result, "pf_001")
        self.assertFalse(item["current"])
        self.assertIn("attribution_uncertain", item["reason_codes"])

    def test_annotation_stays_current_but_uncertain(self) -> None:
        evidence = build(
            [fact("pf_001", phase_ref="ph_002", attribution="annotation", operation="attest")],
            phase_orders=CHAIN,
        )
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported"})
        item = item_for(result, "pf_001")
        self.assertTrue(item["current"])
        self.assertEqual(item["certainty"], "uncertain")
        self.assertIn("attribution_uncertain", item["reason_codes"])


class PhaseModeTests(unittest.TestCase):
    def test_process_mode_shows_every_stage_and_not_only_the_last(self) -> None:
        evidence = build(
            [
                fact("pf_001", phase_ref="ph_001", value="建威中郎將"),
                fact("pf_002", phase_ref="ph_002", value="偏將軍"),
            ],
            phase_orders=CHAIN,
        )
        reading_manifest = manifest(
            "ph_002", unit_phase={"mode": "process", "phase_ids": ["ph_001", "ph_002"]}
        )
        result = compile_(
            evidence,
            {**CHAIN_ASSESSMENTS, "pf_001": "supported", "pf_002": "supported"},
            reading_manifest=reading_manifest,
        )
        current = {entry["value"] for entry in result["items"] if entry["current"]}
        self.assertEqual(current, {"建威中郎將", "偏將軍"})

    def test_unknown_mode_does_not_carry_a_previous_phase(self) -> None:
        evidence = build([fact("pf_001", phase_ref="ph_002")], phase_orders=CHAIN)
        reading_manifest = manifest(
            "ph_002", unit_phase={"mode": "unknown", "phase_ids": ["ph_002"]}
        )
        result = compile_(
            evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported"}, reading_manifest=reading_manifest
        )
        item = item_for(result, "pf_001")
        self.assertFalse(item["current"])
        self.assertIn("order_unknown", item["reason_codes"])

    def test_ambiguous_mode_presents_material_without_a_unity(self) -> None:
        evidence = build([fact("pf_001", phase_ref="ph_001")], phase_orders=CHAIN)
        reading_manifest = manifest(
            "ph_001", unit_phase={"mode": "ambiguous", "phase_ids": ["ph_001", "ph_002"]}
        )
        result = compile_(
            evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported"}, reading_manifest=reading_manifest
        )
        item = item_for(result, "pf_001")
        self.assertFalse(item["current"])
        self.assertIn("order_unknown", item["reason_codes"])

    def test_rerun_of_same_unit_is_identical(self) -> None:
        evidence = build([fact("pf_001", phase_ref="ph_002")], phase_orders=CHAIN)
        reading_manifest = manifest(
            "ph_002", unit_phase={"mode": "single", "phase_ids": ["ph_002"]}
        )
        first = compile_(evidence, {"pf_001": "supported"}, reading_manifest=reading_manifest)
        second = compile_(evidence, {"pf_001": "supported"}, reading_manifest=reading_manifest)
        self.assertEqual(first, second)


class EndAndReappointmentTests(unittest.TestCase):
    def test_targeted_end_closes_only_the_same_key(self) -> None:
        evidence = build(
            [
                fact("pf_001", phase_ref="ph_001", value="建威中郎將"),
                fact("pf_002", phase_ref="ph_001", value="偏將軍"),
                fact("pf_003", phase_ref="ph_002", value="建威中郎將", operation="end"),
            ],
            phase_orders=CHAIN,
        )
        result = compile_(
            evidence,
            {**CHAIN_ASSESSMENTS, "pf_001": "supported", "pf_002": "supported", "pf_003": "supported"},
        )
        item_a = item_for(result, "pf_001")
        item_b = item_for(result, "pf_002")
        self.assertFalse(item_a["current"])
        self.assertFalse(item_b["current"])
        ends = [c for c in result["changes"] if c["operation"] == "end"]
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0]["from_phase_id"], "ph_001")

    def test_proven_end_after_current_keeps_the_tenure_current(self) -> None:
        evidence = build(
            [
                fact("pf_001", phase_ref="ph_001", value="建威中郎將"),
                fact("pf_002", phase_ref="ph_003", value="建威中郎將", operation="end"),
            ],
            phase_orders=CHAIN,
        )
        result = compile_(
            evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported", "pf_002": "supported"}
        )
        item = item_for(result, "pf_001")
        self.assertTrue(item["current"])
        self.assertEqual(item["certainty"], "clear")

    def test_reappointment_after_end_forms_a_new_current_tenure(self) -> None:
        evidence = build(
            [
                fact("pf_001", phase_ref="ph_001", value="偏將軍"),
                fact("pf_002", phase_ref="ph_002", value="偏將軍", operation="end"),
                fact("pf_003", phase_ref="ph_003", value="偏將軍"),
            ],
            phase_orders=CHAIN,
        )
        result = compile_(
            evidence,
            {
                **CHAIN_ASSESSMENTS,
                "pf_001": "supported",
                "pf_002": "supported",
                "pf_003": "supported",
            },
            reading_manifest=manifest("ph_003"),
        )
        self.assertFalse(item_for(result, "pf_001")["current"])
        self.assertTrue(item_for(result, "pf_003")["current"])
        self.assertEqual(item_for(result, "pf_003")["certainty"], "clear")

    def test_concurrent_offices_coexist(self) -> None:
        evidence = build(
            [
                fact("pf_001", phase_ref="ph_002", value="偏將軍"),
                fact("pf_002", phase_ref="ph_002", value="南郡太守"),
            ],
            phase_orders=CHAIN,
        )
        result = compile_(
            evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported", "pf_002": "supported"}
        )
        current_values = {entry["value"] for entry in result["items"] if entry["current"]}
        self.assertEqual(current_values, {"偏將軍", "南郡太守"})

    def test_reported_end_does_not_close_a_narrated_tenure(self) -> None:
        evidence = build(
            [
                fact("pf_001", phase_ref="ph_001", value="左將軍"),
                fact(
                    "pf_002",
                    phase_ref="ph_002",
                    value="左將軍",
                    operation="end",
                    qualification="reported",
                ),
            ],
            phase_orders=CHAIN,
        )
        result = compile_(
            evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported", "pf_002": "supported"}
        )
        item = item_for(result, "pf_001")
        self.assertEqual(item["reason_codes"], ["tenure_unproven"])
        end = [c for c in result["changes"] if c["operation"] == "end"][0]
        self.assertIn("attribution_uncertain", end["reason_codes"])

    def test_affiliation_end_only_affects_its_relation_target(self) -> None:
        evidence = build(
            [
                fact(
                    "pf_001",
                    phase_ref="ph_001",
                    dimension="affiliation",
                    value=None,
                    relation="serves",
                    target="田楷",
                    target_ref={"kind": "entity", "ref": "ent_tian"},
                ),
                fact(
                    "pf_002",
                    phase_ref="ph_001",
                    dimension="affiliation",
                    value=None,
                    relation="attached_to",
                    target="陶謙",
                    target_ref={"kind": "entity", "ref": "ent_tao"},
                ),
                fact(
                    "pf_003",
                    phase_ref="ph_002",
                    dimension="affiliation",
                    value=None,
                    relation="serves",
                    target="田楷",
                    target_ref={"kind": "entity", "ref": "ent_tian"},
                    operation="end",
                ),
            ],
            phase_orders=CHAIN,
        )
        result = compile_(
            evidence,
            {
                **CHAIN_ASSESSMENTS,
                "pf_001": "supported",
                "pf_002": "supported",
                "pf_003": "supported",
            },
            canonical_map={
                PERSON: PERSON_ID,
                "ent_tian": "0192f0a0-0000-7000-8000-00000000d001",
                "ent_tao": "0192f0a0-0000-7000-8000-00000000d002",
            },
        )
        self.assertFalse(item_for(result, "pf_001")["current"])
        self.assertFalse(item_for(result, "pf_002")["current"])


class CanonicalKeyRegressionTests(unittest.TestCase):
    """Blocker 1: two local refs to one canonical office must close."""

    CANONICAL = {
        PERSON: PERSON_ID,
        "ent_office": "0192f0a0-0000-7000-8000-000000000aaa",
    }

    def test_end_matches_by_canonical_office_id(self) -> None:
        evidence = build(
            [
                fact(
                    "pf_001",
                    phase_ref="ph_001",
                    value=None,
                    value_ref={"kind": "entity", "ref": "local_office_a"},
                ),
                fact(
                    "pf_002",
                    phase_ref="ph_002",
                    value=None,
                    value_ref={"kind": "entity", "ref": "local_office_b"},
                    operation="end",
                ),
            ],
            phase_orders=CHAIN,
        )
        canonical = dict(self.CANONICAL)
        canonical["local_office_a"] = self.CANONICAL["ent_office"]
        canonical["local_office_b"] = self.CANONICAL["ent_office"]
        result = compile_(
            evidence,
            {**CHAIN_ASSESSMENTS, "pf_001": "supported", "pf_002": "supported"},
            canonical_map=canonical,
        )
        grant = item_for(result, "pf_001")
        self.assertFalse(grant["current"])
        ends = [c for c in result["changes"] if c["operation"] == "end"]
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0]["from_phase_id"], "ph_001")

    def test_reappointment_matches_by_canonical_office_id(self) -> None:
        evidence = build(
            [
                fact(
                    "pf_001",
                    phase_ref="ph_001",
                    value=None,
                    value_ref={"kind": "entity", "ref": "local_office_a"},
                ),
                fact(
                    "pf_002",
                    phase_ref="ph_002",
                    value=None,
                    value_ref={"kind": "entity", "ref": "local_office_b"},
                    operation="end",
                ),
                fact(
                    "pf_003",
                    phase_ref="ph_003",
                    value=None,
                    value_ref={"kind": "entity", "ref": "local_office_a"},
                ),
            ],
            phase_orders=CHAIN,
        )
        canonical = dict(self.CANONICAL)
        canonical["local_office_a"] = self.CANONICAL["ent_office"]
        canonical["local_office_b"] = self.CANONICAL["ent_office"]
        result = compile_(
            evidence,
            {
                **CHAIN_ASSESSMENTS,
                "pf_001": "supported",
                "pf_002": "supported",
                "pf_003": "supported",
            },
            canonical_map=canonical,
            reading_manifest=manifest("ph_003"),
        )
        self.assertFalse(item_for(result, "pf_001")["current"])
        self.assertTrue(item_for(result, "pf_003")["current"])

    def test_different_canonical_offices_do_not_close(self) -> None:
        evidence = build(
            [
                fact(
                    "pf_001",
                    phase_ref="ph_001",
                    value=None,
                    value_ref={"kind": "entity", "ref": "local_office_a"},
                ),
                fact(
                    "pf_002",
                    phase_ref="ph_002",
                    value=None,
                    value_ref={"kind": "entity", "ref": "local_office_c"},
                    operation="end",
                ),
            ],
            phase_orders=CHAIN,
        )
        canonical = dict(self.CANONICAL)
        canonical["local_office_a"] = self.CANONICAL["ent_office"]
        canonical["local_office_c"] = "0192f0a0-0000-7000-8000-000000000ccc"
        result = compile_(
            evidence,
            {**CHAIN_ASSESSMENTS, "pf_001": "supported", "pf_002": "supported"},
            canonical_map=canonical,
        )
        self.assertEqual(item_for(result, "pf_001")["reason_codes"], ["tenure_unproven"])

    def test_affiliation_target_uses_canonical_id(self) -> None:
        evidence = build(
            [
                fact(
                    "pf_001",
                    phase_ref="ph_001",
                    dimension="affiliation",
                    value=None,
                    relation="serves",
                    target_ref={"kind": "entity", "ref": "local_lord_a"},
                ),
                fact(
                    "pf_002",
                    phase_ref="ph_002",
                    dimension="affiliation",
                    value=None,
                    relation="serves",
                    target_ref={"kind": "entity", "ref": "local_lord_b"},
                    operation="end",
                ),
            ],
            phase_orders=CHAIN,
        )
        canonical = {
            PERSON: PERSON_ID,
            "local_lord_a": "0192f0a0-0000-7000-8000-000000000bbb",
            "local_lord_b": "0192f0a0-0000-7000-8000-000000000bbb",
        }
        result = compile_(
            evidence,
            {**CHAIN_ASSESSMENTS, "pf_001": "supported", "pf_002": "supported"},
            canonical_map=canonical,
        )
        self.assertFalse(item_for(result, "pf_001")["current"])
        self.assertEqual(
            item_for(result, "pf_001")["target_id"], "0192f0a0-0000-7000-8000-000000000bbb"
        )


class DtoContractRegressionTests(unittest.TestCase):
    """Blocker 2: the compiled output must be directly consumable DTOs."""

    def _compiled(self) -> dict:
        continuity = {
            "assertion_id": "pc_001",
            "fact_ref": "pf_001",
            "start_phase_ref": "ph_001",
            "end_phase_ref": None,
        }
        evidence = build(
            [
                fact("pf_001", phase_ref="ph_001", value="建威中郎將", claim_refs=["clm_001"]),
                fact("pf_002", phase_ref="ph_002", value="偏將軍", claim_refs=["clm_002"]),
                fact("pf_003", phase_ref="ph_002", value="建威中郎將", operation="end"),
                fact(
                    "pf_004",
                    phase_ref="ph_002",
                    dimension="affiliation",
                    value=None,
                    relation="serves",
                    target="孫權",
                    target_ref={"kind": "entity", "ref": "ent_lord"},
                ),
            ],
            phase_orders=CHAIN,
            continuities=[continuity],
        )
        return compile_(
            evidence,
            {
                **CHAIN_ASSESSMENTS,
                "pc_001": "supported",
                "pf_001": "supported",
                "pf_002": "supported",
                "pf_003": "supported",
                "pf_004": "supported",
            },
            canonical_map={PERSON: PERSON_ID, "ent_lord": "0192f0a0-0000-7000-8000-000000000ddd"},
        )

    def test_items_and_changes_validate_as_t01_dto(self) -> None:
        result = self._compiled()
        self.assertTrue(result["items"])
        for item in result["items"]:
            assert_dto(self, "state_item", item)
        for change in result["changes"]:
            assert_dto(self, "state_change", change)

    def test_start_identity_and_change_have_distinct_ids_and_independent_evidence(self) -> None:
        evidence = build([fact("pf_001", phase_ref="ph_002")], phase_orders=CHAIN)
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported"})
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(len(result["changes"]), 1)
        identity, change = result["items"][0], result["changes"][0]
        self.assertNotEqual(identity["item_id"], change["item_id"])
        self.assertEqual(identity["item_id"], P.item_id_for(
            chapter_id=CHAPTER_ID, fact_ref="pf_001", dimension="office",
            phase_id="ph_002", person_ref=PERSON, operation="start"))
        self.assertEqual(identity["source_facts"], change["source_facts"])
        item_ids = {identity["item_id"], change["item_id"]}
        self.assertEqual(set(result["reasoning"]), item_ids)
        by_item = {entry["item_id"]: entry["descriptors"] for entry in result["evidence"]}
        self.assertEqual(set(by_item), item_ids)
        descriptor_ids = set()
        for item_id in item_ids:
            self.assertEqual(result["reasoning"][item_id]["assessment"], "supported")
            self.assertEqual(result["reasoning"][item_id]["source_facts"][0]["fact_ref"], "pf_001")
            self.assertEqual(len(by_item[item_id]), 1)
            descriptor = by_item[item_id][0]
            self.assertEqual(descriptor["anchor_id"], ANCHOR["anchor_id"])
            self.assertEqual(descriptor["quote"], ANCHOR["quote"])
            assert_dto(self, "evidence_descriptor", descriptor)
            descriptor_ids.add(descriptor["descriptor_id"])
        self.assertEqual(len(descriptor_ids), 2)
        self.assertEqual({entry["item_id"] for entry in result["people"][PERSON_ID]["evidence"]}, item_ids)
        self.assertEqual(set(result["people"][PERSON_ID]["reasoning"]), item_ids)

    def test_item_has_exactly_the_allowed_fields(self) -> None:
        result = self._compiled()
        allowed = {
            "item_id",
            "person_id",
            "dimension",
            "value",
            "relation",
            "target",
            "target_id",
            "qualification",
            "certainty",
            "reason_codes",
            "reason_text",
            "phase_ids",
            "current",
            "source_facts",
            "evidence_count",
            "evidence_cursor",
        }
        for item in result["items"]:
            self.assertEqual(set(item), allowed)
            self.assertIn("evidence_cursor", item)
            self.assertIsNone(item["evidence_cursor"])
            for source in item["source_facts"]:
                assert_dto(self, "source_fact_ref", source)

    def test_evidence_descriptors_validate_and_carry_publication(self) -> None:
        result = self._compiled()
        self.assertTrue(result["evidence"])
        for entry in result["evidence"]:
            self.assertTrue(entry["descriptors"])
            for descriptor in entry["descriptors"]:
                assert_dto(self, "evidence_descriptor", descriptor)
                self.assertEqual(descriptor["source_publication_id"], PUBLICATION_ID)
                self.assertEqual(descriptor["source_title"], SOURCE_TITLE)
                self.assertEqual(descriptor["anchor_id"], ANCHOR["anchor_id"])

    def test_reasoning_carries_assessment_continuity_and_end_basis(self) -> None:
        result = self._compiled()
        grant = item_for(result, "pf_001")
        reasoning = result["reasoning"][grant["item_id"]]
        self.assertEqual(reasoning["assessment"], "supported")
        self.assertEqual(
            reasoning["continuity"],
            [{"assertion_id": "pc_001", "start_phase_id": "ph_001", "end_phase_id": None}],
        )
        self.assertEqual(reasoning["source_facts"][0]["chapter_publication_id"], PUBLICATION_ID)
        self.assertEqual(reasoning["source_facts"][0]["assessment"], "supported")
        end = [c for c in result["changes"] if c["operation"] == "end"][0]
        end_reasoning = result["reasoning"][end["item_id"]]
        self.assertEqual(end_reasoning["assessment"], "supported")
        self.assertEqual(end_reasoning["from_phase_id"], "ph_001")
        self.assertEqual(end_reasoning["source_facts"][0]["fact_ref"], "pf_003")

    def test_source_fact_requires_a_publication(self) -> None:
        evidence = build([fact("pf_001", phase_ref="ph_002")], phase_orders=CHAIN)
        entry = evidence["facts"][0]
        entry.pop("chapter_publication_id")
        with self.assertRaises(PersistenceError):
            PP.compile_person_state_projection(
                evidence,
                {**CHAIN_ASSESSMENTS, "pf_001": "supported"},
                {PERSON: PERSON_ID},
                {"current_phase_id": "ph_002"},
            )

    def test_place_items_validate_as_t01_dto(self) -> None:
        evidence = build(
            [
                fact(
                    "pf_001",
                    phase_ref="ph_002",
                    dimension="administration",
                    value="南郡",
                    value_ref={"kind": "entity", "ref": "ent_place"},
                )
            ],
            phase_orders=CHAIN,
        )
        result = compile_(
            evidence,
            {**CHAIN_ASSESSMENTS, "pf_001": "supported"},
            canonical_map={PERSON: PERSON_ID, "ent_place": "南郡"},
        )
        self.assertTrue(result["places"])
        for place in result["places"]:
            assert_dto(self, "place_state_item", place)
        self.assertEqual({}, result["people"])
        self.assertEqual([], result["items"])
        self.assertEqual([], result["changes"])


class IntegrationShapeTests(unittest.TestCase):
    def test_value_ref_resolves_display_label(self) -> None:
        entry = fact("pf_001", phase_ref="ph_002", value=None)
        entry["value_ref"] = {"kind": "entity", "ref": "ent_office"}
        evidence = build([entry], phase_orders=CHAIN)
        result = compile_(
            evidence,
            {**CHAIN_ASSESSMENTS, "pf_001": "supported"},
            canonical_map={
                PERSON: PERSON_ID,
                "ent_office": "0192f0a0-0000-7000-8000-000000000aaaa",
                "labels": {"ent_office": "偏將軍"},
            },
        )
        self.assertEqual(item_for(result, "pf_001")["value"], "偏將軍")

    def test_nested_person_states_and_origin_provenance_are_accepted(self) -> None:
        entry = fact("pf_001", phase_ref="ph_002")
        for key in ("chapter_id", "revision_id", "chapter_publication_id", "anchor_ids", "anchors"):
            entry.pop(key)
        entry["origin"] = {
            "chapter_id": CHAPTER_ID,
            "origin_revision_id": REVISION_ID,
            "chapter_publication_id": PUBLICATION_ID,
            "anchor_ids": [ANCHOR["anchor_id"]],
            "anchors": [ANCHOR],
        }
        inner = build([entry], phase_orders=CHAIN)
        result = compile_(
            {"person_states": inner},
            {**CHAIN_ASSESSMENTS, "pf_001": "supported"},
        )
        source = result["items"][0]["source_facts"][0]
        self.assertEqual(source["chapter_id"], CHAPTER_ID)
        self.assertEqual(source["revision_id"], REVISION_ID)
        self.assertEqual(source["chapter_publication_id"], PUBLICATION_ID)
        self.assertTrue(result["evidence"][0]["descriptors"])

    def test_assembled_fact_id_shape_is_accepted(self) -> None:
        entry = fact("pf_001", phase_ref="ph_002")
        entry["fact_id"] = entry.pop("fact_ref")
        entry["origin"] = {
            "chapter_id": CHAPTER_ID,
            "origin_revision_id": REVISION_ID,
        }
        evidence = build([entry], phase_orders=CHAIN)
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported"})
        self.assertTrue(item_for(result, "pf_001")["current"])
        assert_dto(self, "state_item", result["items"][0])

    def test_reading_manifest_units_supply_publication_and_title(self) -> None:
        entry = fact("pf_001", phase_ref="ph_002")
        entry.pop("chapter_publication_id")
        entry.pop("source_title")
        entry.pop("anchors")
        entry["anchor_ids"] = []
        evidence = build([entry], phase_orders=CHAIN)
        reading_manifest = {
            "current_phase_id": "ph_002",
            "units": [
                {
                    "unit_id": "t_001",
                    "chapter_id": CHAPTER_ID,
                    "publication_id": PUBLICATION_ID,
                    "source_title": SOURCE_TITLE,
                }
            ],
        }
        result = compile_(
            evidence,
            {**CHAIN_ASSESSMENTS, "pf_001": "supported"},
            reading_manifest=reading_manifest,
        )
        self.assertEqual(
            result["items"][0]["source_facts"][0]["chapter_publication_id"], PUBLICATION_ID
        )

    def test_reading_manifest_entity_labels_resolve_display(self) -> None:
        entry = fact("pf_001", phase_ref="ph_002", value=None)
        entry["value_ref"] = {"kind": "entity", "ref": "ent_office"}
        evidence = build([entry], phase_orders=CHAIN)
        result = compile_(
            evidence,
            {**CHAIN_ASSESSMENTS, "pf_001": "supported"},
            reading_manifest=manifest("ph_002", entity_labels={"ent_office": "偏將軍"}),
        )
        self.assertEqual(item_for(result, "pf_001")["value"], "偏將軍")


class RealReadingManifestRegressionTests(unittest.TestCase):
    """Real assembly -> R2 reading-manifest -> projection chain.

    The reading manifest is produced by the actual
    :func:`reading_projection.compile_reading_projection` (``chapters``
    list + nested ``manifest.source_title``), and the person-state evidence
    uses real assembled anchors, so publication/title/anchor resolution is
    exercised against the production shapes instead of a hand-made map.
    """

    C2R2_FIXTURES = HERE.parent / "ingestion" / "fixtures" / "c2r2-contract"
    STREAM = "0192f0a0-0000-7000-8000-00000000aa01"

    def _real_inputs(self) -> tuple[dict, dict, dict]:
        request = json.loads(
            (self.C2R2_FIXTURES / "request.json").read_text(encoding="utf-8")
        )
        candidate = json.loads(
            (self.C2R2_FIXTURES / "candidate-valid.json").read_text(encoding="utf-8")
        )
        artifact = RC.accept_reading_candidate(
            request,
            candidate,
            producing_run={"run_id": "r", "model": "m", "prompt_schema_version": "v"},
        )
        plan = {
            "version": "c2r1-chapters-v1",
            "plan_sha256": "p" * 64,
            "revision_id": request["revision_id"],
            "source_sha256": request["source_sha256"],
            "normalized_sha256": request["normalized_sha256"],
            "chapters": [
                {
                    "chapter_id": request["chapter_id"],
                    "chapter_index": 0,
                    "title": "contract chapter",
                    "start": 0,
                    "end": 36,
                    "content_sha256": request["normalized_sha256"],
                }
            ],
        }

        def canonical(prefix: str, index: int) -> str:
            return f"0192f0a0-0000-7000-8000-{prefix}{index:011x}"

        catalog = {
            "schema": "chronicle.canonical-catalog",
            "version": "0.1",
            "canonical_entities": [
                {
                    "canonical_id": canonical("e", index),
                    "representations": [
                        {"bundle": "c1rev-demo", "ref": f"ent_{index:06d}"}
                    ],
                }
                for index in range(1, 5)
            ],
            "canonical_events": [
                {
                    "canonical_id": canonical("f", index),
                    "representations": [
                        {"bundle": "c1rev-demo", "ref": f"evt_{index:06d}"}
                    ],
                }
                for index in range(1, 5)
            ],
            "event_relations": [],
            "warnings": [],
        }
        projection = RP.compile_reading_projection(
            accepted_artifacts=[artifact],
            chapter_plan=plan,
            catalog=catalog,
            stream_id=self.STREAM,
            publication_by_chapter={request["chapter_id"]: PUBLICATION_ID},
            bundle_label="c1rev-demo",
        )
        assembled = A.assemble_chapters(accepted_artifacts=[artifact], chapter_plan=plan)
        return request, projection, assembled

    def _evidence_from_real_anchors(self, request: dict, assembled: dict) -> dict:
        anchors = [
            entry
            for entry in assembled["anchors"]
            if entry.get("chapter_id") == request["chapter_id"]
        ]
        self.assertTrue(anchors)
        entry = fact("pf_001", phase_ref="ph_001", anchors=[anchors[0]])
        entry["chapter_id"] = request["chapter_id"]
        entry["revision_id"] = request["revision_id"]
        entry.pop("chapter_publication_id")
        entry.pop("source_title")
        return {
            "phases": [{"phase_id": "ph_001"}],
            "phase_orders": [],
            "unit_phases": [],
            "facts": [entry],
            "continuities": [],
            "disagreements": [],
        }

    def test_r2_manifest_only_chapters_resolves_publication_and_title(self) -> None:
        request, projection, assembled = self._real_inputs()
        evidence = self._evidence_from_real_anchors(request, assembled)
        reading_manifest = dict(projection["manifest"])
        reading_manifest["current_phase_id"] = "ph_001"
        result = PP.compile_person_state_projection(
            evidence, {"pf_001": "supported"}, {PERSON: PERSON_ID}, reading_manifest
        )
        source = result["items"][0]["source_facts"][0]
        self.assertEqual(source["chapter_publication_id"], PUBLICATION_ID)
        self.assertEqual(source["chapter_id"], request["chapter_id"])
        descriptors = result["evidence"][0]["descriptors"]
        self.assertTrue(descriptors)
        self.assertEqual(descriptors[0]["source_publication_id"], PUBLICATION_ID)
        self.assertEqual(
            descriptors[0]["source_title"], projection["manifest"]["source_title"]
        )
        assert_dto(self, "evidence_descriptor", descriptors[0])

    def test_r2_full_projection_reads_nested_manifest_title(self) -> None:
        request, projection, assembled = self._real_inputs()
        evidence = self._evidence_from_real_anchors(request, assembled)
        reading_manifest = dict(projection)
        reading_manifest["current_phase_id"] = "ph_001"
        result = PP.compile_person_state_projection(
            evidence, {"pf_001": "supported"}, {PERSON: PERSON_ID}, reading_manifest
        )
        descriptors = result["evidence"][0]["descriptors"]
        self.assertTrue(descriptors)
        self.assertEqual(
            descriptors[0]["source_title"], projection["manifest"]["source_title"]
        )

    def test_r2_projection_without_current_phase_still_emits_evidence(self) -> None:
        request, projection, assembled = self._real_inputs()
        evidence = self._evidence_from_real_anchors(request, assembled)
        # Passing the projection as-is (no explicit current phase) must not
        # fail closed and must still expose the anchor evidence.
        result = PP.compile_person_state_projection(
            evidence, {"pf_001": "supported"}, {PERSON: PERSON_ID}, projection
        )
        self.assertTrue(result["evidence"])
        self.assertTrue(result["evidence"][0]["descriptors"])
        self.assertEqual(result["items"][0]["evidence_count"], 1)


class DeterminismAndBoundsTests(unittest.TestCase):
    def test_projection_hash_is_stable_for_identical_input(self) -> None:
        evidence = build(
            [
                fact("pf_001", phase_ref="ph_001", value="建威中郎將"),
                fact("pf_002", phase_ref="ph_002", value="偏將軍"),
            ],
            phase_orders=CHAIN,
        )
        assessments = {**CHAIN_ASSESSMENTS, "pf_001": "supported", "pf_002": "supported"}
        first = compile_(evidence, assessments)
        second = compile_(evidence, assessments)
        self.assertEqual(first, second)
        self.assertEqual(first["projection_sha256"], second["projection_sha256"])

    def test_item_ids_are_stable_and_keyed_by_fact(self) -> None:
        evidence = build([fact("pf_001", phase_ref="ph_002")], phase_orders=CHAIN)
        result = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported"})
        again = compile_(evidence, {**CHAIN_ASSESSMENTS, "pf_001": "supported"})
        self.assertEqual(item_for(result, "pf_001")["item_id"], item_for(again, "pf_001")["item_id"])

    def test_phase_cycle_fails_closed(self) -> None:
        evidence = build(
            [fact("pf_001", phase_ref="ph_002")],
            phase_orders=CHAIN + [order("po_003", "ph_003", "ph_001")],
        )
        with self.assertRaises(PersistenceError):
            compile_(evidence, {**CHAIN_ASSESSMENTS, "po_003": "supported", "pf_001": "supported"})

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


class ChapterScopeTests(unittest.TestCase):
    """A per-unit compile must not leak another chapter's phases/facts.

    The assembled ``person_states`` evidence is revision-wide, while
    ``build_person_state_manifest`` compiles once per reading unit. Cross
    chapter phases have no order edge, so without a chapter scope every unit
    would treat the other chapters' facts as ``order_unknown`` and expose
    persons that are not in that unit's context (the read API fails closed).
    """

    OTHER_CHAPTER = "ch_756922e9af0d759d29d74760"
    OTHER_PERSON = "ent_003"
    OTHER_PERSON_ID = "0192f0a0-0000-7000-8000-00000000cc08"

    def _two_chapter_evidence(self) -> dict:
        own = fact("pf_001", phase_ref="ph_001")
        own["origin"] = {
            "chapter_id": CHAPTER_ID,
            "chapter_index": 0,
            "origin_ref": "pf_001",
            "anchor_ids": [ANCHOR["anchor_id"]],
            "anchors": [ANCHOR],
        }
        foreign = fact("pf_002", phase_ref="ph_101")
        foreign["person_ref"] = {"kind": "entity", "ref": self.OTHER_PERSON}
        foreign["person_key"] = self.OTHER_PERSON
        foreign["chapter_id"] = self.OTHER_CHAPTER
        foreign["origin"] = {
            "chapter_id": self.OTHER_CHAPTER,
            "chapter_index": 1,
            "origin_ref": "pf_002",
            "anchor_ids": [ANCHOR["anchor_id"]],
            "anchors": [ANCHOR],
        }
        return {
            "phases": [
                {"phase_id": "ph_001", "origin": {"chapter_id": CHAPTER_ID}},
                {"phase_id": "ph_101", "origin": {"chapter_id": self.OTHER_CHAPTER}},
            ],
            "phase_orders": [
                {
                    "assertion_id": "po_001",
                    "earlier_phase_ref": "ph_001",
                    "later_phase_ref": "ph_101",
                    "origin": {"chapter_id": CHAPTER_ID},
                }
            ],
            "unit_phases": [],
            "facts": [own, foreign],
            "continuities": [],
            "disagreements": [],
        }

    def test_chapter_scope_excludes_other_chapter_facts(self) -> None:
        evidence = self._two_chapter_evidence()
        scoped = compile_(
            evidence,
            {"pf_001": "supported", "pf_002": "supported"},
            canonical_map={PERSON: PERSON_ID, self.OTHER_PERSON: self.OTHER_PERSON_ID},
            reading_manifest=manifest(
                current="ph_001",
                chapter_id=CHAPTER_ID,
                unit_phase={"mode": "single", "phase_ids": ["ph_001"]},
            ),
        )
        self.assertIn("pf_001", [entry["source_facts"][0]["fact_ref"] for entry in scoped["items"]])
        self.assertNotIn("pf_002", [entry["source_facts"][0]["fact_ref"] for entry in scoped["items"]])
        self.assertEqual(set(scoped["people"]), {PERSON_ID})

    def test_without_a_chapter_scope_the_revision_wide_evidence_leaks(self) -> None:
        # Documents the defect the scope fixes: with no unit chapter the other
        # chapter's fact is classified order_unknown and included.
        evidence = self._two_chapter_evidence()
        leaked = compile_(
            evidence,
            {"pf_001": "supported", "pf_002": "supported"},
            canonical_map={PERSON: PERSON_ID, self.OTHER_PERSON: self.OTHER_PERSON_ID},
            reading_manifest=manifest(
                current="ph_001",
                unit_phase={"mode": "single", "phase_ids": ["ph_001"]},
            ),
        )
        self.assertIn(self.OTHER_PERSON_ID, set(leaked["people"]))


if __name__ == "__main__":
    unittest.main()
