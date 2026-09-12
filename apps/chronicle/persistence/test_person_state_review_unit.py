"""Unit tests for Chronicle C2-R3-T06 person-state review core.

Covers the pure plan / decision / preview contract from
``person-state-reading.md`` section 5 and the C2-R3-T06 task note:

- the frozen ``c2r3-person-state-review-plan-v1`` binds every binding hash and
  covers every candidate key exactly once, deterministically;
- a tampered candidate key, duplicate candidate or changed binding hash fails
  closed before any database read;
- the default + override decision expansion is exact, override rationales are
  mandatory, unknown/duplicate candidates are rejected and an omitted default
  can never become ``supported``;
- the T04 compiler preview turns only explicitly supported facts into a clear
  current identity and never leaks a future phase.

No database, model or network is used.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import person_state_contract as contract  # noqa: E402
import person_state_review as review  # noqa: E402
from common import PersistenceConflict, PersistenceError, sha256_json  # noqa: E402

REVISION = "rev-r3-t06"
SHA = "a" * 64
NORM = "b" * 64
CATALOG = "c" * 64
CHAPTER = "ch_000000000000000000000001"
JOB = "11111111-1111-7111-8111-111111111111"


def _anchor_id(counter: int) -> str:
    return "anc_" + f"{counter:016x}"


def _person_states(counter: int) -> tuple[dict, list[dict], int]:
    anchors: list[dict] = []
    candidates: list[dict] = []

    def add(kind: str, item_ref: str, phase_ids: list[str], fact_refs: list[str]) -> None:
        nonlocal counter
        anchor_id = _anchor_id(counter)
        counter += 1
        candidate = {
            "candidate_key": contract.candidate_key_for(
                kind=kind, chapter_id=CHAPTER, item_ref=item_ref, anchor_ids=[anchor_id]
            ),
            "kind": kind,
            "item_ref": item_ref,
            "phase_ids": list(phase_ids),
            "anchor_ids": [anchor_id],
            "source_fact_refs": list(fact_refs),
        }
        candidates.append(candidate)

    person_states = {
        "phases": [
            {"phase_id": "ph_001", "label": "初", "event_refs": [], "source_selections": []},
            {"phase_id": "ph_002", "label": "後", "event_refs": [], "source_selections": []},
        ],
        "phase_orders": [
            {
                "assertion_id": "po_001",
                "earlier_phase_ref": "ph_001",
                "later_phase_ref": "ph_002",
                "source_selections": [],
            }
        ],
        "unit_phases": [
            {
                "block_id": "t_001",
                "mode": "single",
                "phase_refs": ["ph_001"],
                "source_selections": [],
            }
        ],
        "facts": [
            {
                "fact_id": "pf_001",
                "person_ref": {"kind": "entity", "ref": "ent_001"},
                "dimension": "office",
                "value_ref": {"kind": "entity", "ref": "ent_002"},
                "relation": None,
                "target_ref": None,
                "operation": "start",
                "qualification": "ordinary",
                "phase_ref": "ph_001",
                "claim_refs": [],
                "source_selections": [],
                "attribution": "narrator",
            },
            {
                "fact_id": "pf_002",
                "person_ref": {"kind": "entity", "ref": "ent_001"},
                "dimension": "office",
                "value_ref": {"kind": "entity", "ref": "ent_002"},
                "relation": None,
                "target_ref": None,
                "operation": "end",
                "qualification": "ordinary",
                "phase_ref": "ph_002",
                "claim_refs": [],
                "source_selections": [],
                "attribution": "narrator",
            },
            {
                "fact_id": "pf_003",
                "person_ref": {"kind": "entity", "ref": "ent_001"},
                "dimension": "office",
                "value_ref": {"kind": "entity", "ref": "ent_002"},
                "relation": None,
                "target_ref": None,
                "operation": "attest",
                "qualification": "posthumous",
                "phase_ref": "ph_002",
                "claim_refs": [],
                "source_selections": [],
                "attribution": "narrator",
            },
        ],
        "continuities": [
            {
                "assertion_id": "pc_001",
                "fact_ref": "pf_001",
                "start_phase_ref": "ph_001",
                "end_phase_ref": None,
                "source_selections": [],
            }
        ],
        "disagreements": [
            {
                "assertion_id": "pd_001",
                "topic": "任職_月份",
                "fact_refs": ["pf_001", "pf_002"],
                "phase_refs": ["ph_001", "ph_002"],
                "source_selections": [],
            }
        ],
    }
    add("phase", "ph_001", ["ph_001"], [])
    add("phase", "ph_002", ["ph_002"], [])
    add("phase_order", "po_001", ["ph_001", "ph_002"], [])
    add("unit_phase", "t_001", ["ph_001"], [])
    add("fact", "pf_001", ["ph_001"], ["pf_001"])
    add("fact", "pf_002", ["ph_002"], ["pf_002"])
    add("fact", "pf_003", ["ph_002"], ["pf_003"])
    add("continuity", "pc_001", ["ph_001"], ["pf_001"])
    add("disagreement", "pd_001", ["ph_001", "ph_002"], ["pf_001", "pf_002"])
    return person_states, candidates, counter


def _artifact() -> dict:
    person_states, candidates, _ = _person_states(0)
    core = {
        "schema": "chronicle.chapter-artifact",
        "version": "0.3",
        "chapter_id": CHAPTER,
        "revision_id": REVISION,
        "source_sha256": SHA,
        "normalized_sha256": NORM,
        "candidate": {"schema": "chronicle.chapter-candidate", "version": "0.3"},
        "candidate_sha256": sha256_json({"candidate": True}),
        "anchors": [],
        "request_fingerprint": "fp-1",
        "producing_run": {"run_id": "run-1", "model": "m", "prompt_schema_version": "0.3"},
        "reading": {},
        "reading_sha256": sha256_json({}),
        "person_states": person_states,
        "person_states_sha256": sha256_json(person_states),
        "person_state_candidates": candidates,
    }
    artifact = dict(core)
    artifact["artifact_sha256"] = sha256_json(core)
    return artifact


def _assembly() -> dict:
    """Build a minimal but T04-valid assembled namespace for chapter 0."""
    origin = {
        "chapter_id": CHAPTER,
        "chapter_index": 0,
        "origin_revision_id": REVISION,
        "origin_ref": "pf_001",
        "artifact_sha256": "e" * 64,
        "anchor_ids": [],
        "anchors": [],
    }
    person_states = {
        "phases": [
            {"phase_id": "ph_000001", "label": "初", "event_refs": [], "source_selections": []},
            {"phase_id": "ph_000002", "label": "後", "event_refs": [], "source_selections": []},
        ],
        "phase_orders": [
            {
                "assertion_id": "po_000001",
                "earlier_phase_ref": "ph_000001",
                "later_phase_ref": "ph_000002",
                "source_selections": [],
            }
        ],
        "unit_phases": [
            {
                "block_id": "t_000001",
                "mode": "single",
                "phase_refs": ["ph_000001"],
                "source_selections": [],
            }
        ],
        "facts": [
            {
                "fact_id": "pf_000001",
                "person_ref": {"kind": "entity", "ref": "ent_000001"},
                "dimension": "office",
                "value_ref": {"kind": "entity", "ref": "ent_000002"},
                "relation": None,
                "target_ref": None,
                "operation": "start",
                "qualification": "ordinary",
                "phase_ref": "ph_000001",
                "claim_refs": [],
                "source_selections": [],
                "attribution": "narrator",
                "origin": origin,
            },
            {
                "fact_id": "pf_000002",
                "person_ref": {"kind": "entity", "ref": "ent_000001"},
                "dimension": "office",
                "value_ref": {"kind": "entity", "ref": "ent_000002"},
                "relation": None,
                "target_ref": None,
                "operation": "end",
                "qualification": "ordinary",
                "phase_ref": "ph_000002",
                "claim_refs": [],
                "source_selections": [],
                "attribution": "narrator",
                "origin": {**origin, "origin_ref": "pf_002"},
            },
        ],
        "continuities": [
            {
                "assertion_id": "pc_000001",
                "fact_ref": "pf_000001",
                "start_phase_ref": "ph_000001",
                "end_phase_ref": None,
                "source_selections": [],
            }
        ],
        "disagreements": [],
    }
    manifest_items = [
        {"kind": "phase", "origin_ref": "ph_001", "revision_ref": "ph_000001"},
        {"kind": "phase", "origin_ref": "ph_002", "revision_ref": "ph_000002"},
        {"kind": "phase_order", "origin_ref": "po_001", "revision_ref": "po_000001"},
        {"kind": "unit_phase", "origin_ref": "t_001", "revision_ref": "t_000001"},
        {"kind": "fact", "origin_ref": "pf_001", "revision_ref": "pf_000001"},
        {"kind": "fact", "origin_ref": "pf_002", "revision_ref": "pf_000002"},
        {"kind": "fact", "origin_ref": "pf_003", "revision_ref": "pf_000003"},
        {"kind": "continuity", "origin_ref": "pc_001", "revision_ref": "pc_000001"},
        {"kind": "disagreement", "origin_ref": "pd_001", "revision_ref": "pd_000001"},
    ]
    return {
        "person_states": person_states,
        "evidence_manifests": [{"chapter_id": CHAPTER, "items": manifest_items}],
        "report": {"person_states_sha256": sha256_json(person_states)},
    }


def _plan(**overrides) -> dict:
    kwargs = dict(
        job_id=JOB,
        revision_id=REVISION,
        accepted_artifacts=[_artifact()],
        assembly=_assembly(),
        resolution_hashes=["d" * 64],
        base_catalog_sha=CATALOG,
    )
    kwargs.update(overrides)
    return review.build_person_state_review_plan(**kwargs)


def _package(plan: dict) -> dict:
    return plan["packages"][0]


class PersonStateReviewPlanTests(unittest.TestCase):
    def test_plan_covers_every_candidate_exactly_once(self) -> None:
        plan = _plan()
        covered = [
            candidate["candidate_key"]
            for package in plan["packages"]
            for candidate in package["candidates"]
        ]
        self.assertEqual(len(covered), 9)
        self.assertEqual(sorted(covered), sorted(plan["candidate_keys"]))
        self.assertEqual(len(covered), len(set(covered)))
        # One package per natural chapter, candidate keys only.
        self.assertEqual([package["chapter_id"] for package in plan["packages"]], [CHAPTER])
        self.assertTrue(all("kind" in c and "candidate_key" in c for c in _package(plan)["candidates"]))

    def test_plan_is_deterministic(self) -> None:
        first = _plan()
        second = _plan()
        self.assertEqual(first, second)
        self.assertEqual(first["plan_fingerprint"], second["plan_fingerprint"])

    def test_binding_change_breaks_fingerprint(self) -> None:
        baseline = _plan()
        changed = _plan(resolution_hashes=["e" * 64])
        self.assertNotEqual(baseline["plan_fingerprint"], changed["plan_fingerprint"])
        changed_catalog = _plan(base_catalog_sha="f" * 64)
        self.assertNotEqual(baseline["plan_fingerprint"], changed_catalog["plan_fingerprint"])

    def test_predicted_effect_distinguishes_operations(self) -> None:
        candidates = {
            candidate["item_ref"]: candidate
            for candidate in _package(_plan())["candidates"]
            if candidate["kind"] == "fact"
        }
        self.assertEqual(candidates["pf_001"]["predicted_effect"], "current_identity")
        self.assertEqual(candidates["pf_002"]["predicted_effect"], "change")
        self.assertEqual(candidates["pf_003"]["predicted_effect"], "attested_identity")

    def test_tampered_candidate_key_fails_closed(self) -> None:
        plan = _plan()
        plan["packages"][0]["candidates"][0]["candidate_key"] = "psc_" + "0" * 24
        with self.assertRaises(PersistenceConflict):
            review.validate_person_state_review_plan(plan)

    def test_duplicate_candidate_fails_closed(self) -> None:
        artifact = _artifact()
        artifact["person_state_candidates"].append(
            copy.deepcopy(artifact["person_state_candidates"][0])
        )
        with self.assertRaises(PersistenceConflict):
            review.build_person_state_review_plan(
                job_id=JOB,
                revision_id=REVISION,
                accepted_artifacts=[artifact],
                assembly=_assembly(),
                resolution_hashes=["d" * 64],
                base_catalog_sha=CATALOG,
            )

    def test_assembly_report_hash_mismatch_fails_closed(self) -> None:
        assembly = _assembly()
        # Tamper the payload but keep the old report hash: the plan must not
        # freeze a hash that no longer describes the assembled content.
        assembly["person_states"]["facts"][0]["phase_ref"] = "ph_000002"
        with self.assertRaises(PersistenceConflict):
            review.build_person_state_review_plan(
                job_id=JOB,
                revision_id=REVISION,
                accepted_artifacts=[_artifact()],
                assembly=assembly,
                resolution_hashes=["d" * 64],
                base_catalog_sha=CATALOG,
            )

    def test_missing_anchor_premise_fails_closed(self) -> None:
        artifact = _artifact()
        fact = next(
            entry for entry in artifact["person_state_candidates"] if entry["kind"] == "fact"
        )
        fact["anchor_ids"] = []
        with self.assertRaises(PersistenceError):
            review.build_person_state_review_plan(
                job_id=JOB,
                revision_id=REVISION,
                accepted_artifacts=[artifact],
                assembly=_assembly(),
                resolution_hashes=["d" * 64],
                base_catalog_sha=CATALOG,
            )


class PersonStateDecisionTests(unittest.TestCase):
    def test_default_expands_to_every_candidate_and_override_wins(self) -> None:
        package = _package(_plan())
        key = package["candidates"][0]["candidate_key"]
        record = review.normalize_person_state_decision(
            package,
            {
                "default_assessment": "uncertain",
                "overrides": [
                    {"candidate_id": key, "assessment": "supported", "rationale": "直接原文"}
                ],
                "rationale": "",
            },
            plan_fingerprint="fp",
        )
        self.assertEqual(record["default_assessment"], "uncertain")
        self.assertEqual(record["decisions"][key]["assessment"], "supported")
        self.assertEqual(len(record["decisions"]), len(package["candidates"]))
        self.assertTrue(record["decisions"][key]["override"])

    def test_omitted_default_is_rejected(self) -> None:
        package = _package(_plan())
        with self.assertRaises(PersistenceError):
            review.normalize_person_state_decision(
                package, {"overrides": []}, plan_fingerprint="fp"
            )

    def test_unreviewed_cannot_default_supported_without_rationale(self) -> None:
        package = _package(_plan())
        with self.assertRaises(PersistenceError):
            review.normalize_person_state_decision(
                package,
                {"default_assessment": "supported", "overrides": []},
                plan_fingerprint="fp",
            )

    def test_override_requires_known_candidate_and_rationale(self) -> None:
        package = _package(_plan())
        with self.assertRaises(PersistenceError):
            review.normalize_person_state_decision(
                package,
                {
                    "default_assessment": "uncertain",
                    "overrides": [
                        {"candidate_id": "psc_unknown", "assessment": "supported", "rationale": "x"}
                    ],
                },
                plan_fingerprint="fp",
            )
        key = package["candidates"][0]["candidate_key"]
        with self.assertRaises(PersistenceError):
            review.normalize_person_state_decision(
                package,
                {
                    "default_assessment": "uncertain",
                    "overrides": [{"candidate_id": key, "assessment": "supported", "rationale": ""}],
                },
                plan_fingerprint="fp",
            )

    def test_duplicate_override_is_conflict(self) -> None:
        package = _package(_plan())
        key = package["candidates"][0]["candidate_key"]
        override = {"candidate_id": key, "assessment": "supported", "rationale": "x"}
        with self.assertRaises(PersistenceConflict):
            review.normalize_person_state_decision(
                package,
                {"default_assessment": "uncertain", "overrides": [override, dict(override)]},
                plan_fingerprint="fp",
            )


class PersonStatePreviewTests(unittest.TestCase):
    def test_preview_uses_t04_compiler(self) -> None:
        plan = _plan()
        assembly = _assembly()
        decisions = {plan["candidate_keys"][0]: "supported"}
        # Support the start fact and its continuity explicitly.
        for candidate in _package(plan)["candidates"]:
            if candidate["item_ref"] == "pf_001":
                decisions[candidate["candidate_key"]] = "supported"
            elif candidate["item_ref"] == "pc_001":
                decisions[candidate["candidate_key"]] = "supported"
        projection = review.preview_person_state_review(
            plan=plan,
            assembly=assembly,
            decisions=decisions,
            canonical_map={"ent_000001": "person-1", "ent_000002": "office-2"},
            reading_manifest={
                "current_phase_id": "ph_000001",
                "chapter_publication_id": "pub-1",
                "source_title": "周瑜傳",
                "unit_phase": {"mode": "single", "phase_ids": ["ph_000001"]},
            },
        )
        item = projection["items"][0]
        self.assertEqual(item["person_id"], "person-1")
        self.assertEqual(item["certainty"], "clear")
        self.assertTrue(item["current"])

    def test_preview_rejects_drifted_assembly(self) -> None:
        plan = _plan()
        assembly = _assembly()
        assembly["person_states"]["facts"][0]["phase_ref"] = "ph_000002"
        with self.assertRaises(PersistenceConflict):
            review.preview_person_state_review(
                plan=plan,
                assembly=assembly,
                decisions={},
                canonical_map={},
                reading_manifest={},
            )

    def test_preview_default_uncertain_is_not_clear(self) -> None:
        plan = _plan()
        projection = review.preview_person_state_review(
            plan=plan,
            assembly=_assembly(),
            decisions={},
            canonical_map={"ent_000001": "person-1", "ent_000002": "office-2"},
            reading_manifest={
                "current_phase_id": "ph_000001",
                "chapter_publication_id": "pub-1",
                "source_title": "周瑜傳",
                "unit_phase": {"mode": "single", "phase_ids": ["ph_000001"]},
            },
        )
        self.assertTrue(projection["items"])
        self.assertTrue(all(item["certainty"] == "uncertain" for item in projection["items"]))


if __name__ == "__main__":
    unittest.main()
