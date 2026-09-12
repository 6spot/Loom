"""Unit tests for the Chronicle C2-R3-T01 person-state contract (no PostgreSQL).

Covers the third-round machine contract from ``person-state-reading.md``
sections 2-7: 0.3 ``person_states`` validation with the frozen 0.2 reading
semantics reused verbatim, phase-DAG acyclicity, unit-phase coverage,
dimension/subject typing, continuity ordering, program acceptance and
stable review candidate keys, revision remap, the pure projection
(certainty, future leak, tenure and disagreement rules), the bounded
disagreement index, review-scope semantics and the review/public DTO
mirror in ``person-state-types.ts``. Pure functions only: no DB, network,
or model calls.
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import person_state_contract as P  # noqa: E402
import reading_contract as R  # noqa: E402
from common import PersistenceError, sha256_json  # noqa: E402

FIXTURES = HERE.parent / "ingestion" / "fixtures" / "c2r3-contract"
PERSON_STATE_TYPES = HERE.parent / "webapp" / "src" / "lib" / "person-state-types.ts"

STREAM_ID = "0192f0a0-0000-7000-8000-00000000aa01"
CATALOG_SHA = "a" * 64
PUBLICATION_ID = "0192f0a0-0000-7000-8000-00000000bb02"
PERSON_ID = "0192f0a0-0000-7000-8000-00000000cc07"
CHAPTER_ID = "ch_756922e9af0d759d29d7475f"
REVISION_ID = "rev_c2r3_demo_001"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def base() -> tuple[dict, dict]:
    return load("request.json"), load("candidate-valid.json")


def assert_rejected(test: unittest.TestCase, report: dict, category: str) -> None:
    test.assertFalse(report["passed"], json.dumps(report["errors"], ensure_ascii=False))
    test.assertTrue(
        report["errors"].get(category),
        f"expected {category} errors, got {json.dumps(report['errors'], ensure_ascii=False)}",
    )


def evidence_fact(
    fact_ref: str,
    *,
    person_ref: str = "ent_002",
    dimension: str = "office",
    value: str | None = "建威中郎將",
    operation: str = "start",
    qualification: str = "ordinary",
    phase_ref: str = "ph_001",
    relation: str | None = None,
    target: str | None = None,
    attribution: str = "narrator",
) -> dict:
    return {
        "fact_ref": fact_ref,
        "person_ref": {"kind": "entity", "ref": person_ref},
        "person_key": person_ref,
        "dimension": dimension,
        "value": value,
        "relation": relation,
        "target": target,
        "target_ref": None,
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


def projection_inputs(facts: list[dict], *, continuities=None, disagreements=None, current="ph_002"):
    return (
        {
            "phases": [{"phase_id": "ph_001"}, {"phase_id": "ph_002"}, {"phase_id": "ph_003"}],
            "facts": facts,
            "continuities": list(continuities or []),
            "disagreements": list(disagreements or []),
        },
        {"ent_002": PERSON_ID, "ent_005": "0192f0a0-0000-7000-8000-0000000000ee"},
        {"current_phase_id": current, "unit_phase": {}},
    )


class LimitsTests(unittest.TestCase):
    def test_defaults_match_contract_envelope(self) -> None:
        limits = P.PersonStateLimits()
        self.assertEqual(limits.max_phases, 512)
        self.assertEqual(limits.max_facts, 512)
        self.assertEqual(limits.max_assertions, 1024)
        self.assertEqual(limits.max_phases_per_unit, 8)
        self.assertEqual((limits.page_min_limit, limits.page_max_limit), (1, 50))
        self.assertEqual(limits.evidence_page_max_descriptors, 50)
        self.assertEqual(limits.summary_max_items, 3)


class CandidateValidationTests(unittest.TestCase):
    def test_valid_candidate_passes_and_reuses_reading(self) -> None:
        request, candidate = base()
        report = P.validate_person_state_candidate(request, candidate)
        self.assertTrue(report["passed"], json.dumps(report["errors"], ensure_ascii=False))
        self.assertEqual(report["errors"]["reading"], [])
        subset = copy.deepcopy(candidate)
        subset.pop("person_states")
        subset["version"] = "0.2"
        self.assertTrue(R.validate_reading_annotations(request, subset)["passed"])

    def test_second_round_reading_semantics_still_enforced(self) -> None:
        request, candidate = base()
        candidate["reading"]["units"][0]["narrative_time"]["mode"] = "events"
        report = P.validate_person_state_candidate(request, candidate)
        assert_rejected(self, report, "reading")

    def test_negative_fixtures_reject_in_named_category(self) -> None:
        request, _ = base()
        cases = {
            "candidate-missing-unit-phase.json": "person_state_coverage",
            "candidate-phase-cycle.json": "person_state_phase",
            "candidate-unknown-ref.json": "person_state_refs",
            "candidate-wrong-subject.json": "person_state_types",
            "candidate-canonical-id.json": "canonical_id",
            "candidate-recommendation-start.json": "person_state_types",
            "candidate-single-fact-disagreement.json": "person_state_types",
            "candidate-unbound-phase.json": "person_state_phase",
            "candidate-unproven-continuity.json": "person_state_continuity",
            "candidate-url.json": "canonical_id",
        }
        for name, category in cases.items():
            with self.subTest(fixture=name):
                assert_rejected(
                    self, P.validate_person_state_candidate(request, load(name)), category
                )

    def test_model_cannot_write_certainty_or_supported(self) -> None:
        request, candidate = base()
        candidate["person_states"]["facts"][0]["certainty"] = "clear"
        report = P.validate_person_state_candidate(request, candidate)
        assert_rejected(self, report, "canonical_id")
        candidate = base()[1]
        candidate["person_states"]["facts"][0]["supported"] = True
        assert_rejected(
            self, P.validate_person_state_candidate(request, candidate), "canonical_id"
        )

    def test_phase_topological_order_is_deterministic_and_detects_cycle(self) -> None:
        phases = [{"phase_id": "ph_001"}, {"phase_id": "ph_002"}, {"phase_id": "ph_003"}]
        orders = [
            {"assertion_id": "po_001", "earlier_phase_ref": "ph_001", "later_phase_ref": "ph_002"},
            {"assertion_id": "po_002", "earlier_phase_ref": "ph_002", "later_phase_ref": "ph_003"},
        ]
        ordered, errors = P.phase_topological_order(phases, orders)
        self.assertEqual(errors, [])
        self.assertEqual(ordered, ["ph_001", "ph_002", "ph_003"])
        cycle = orders + [
            {"assertion_id": "po_003", "earlier_phase_ref": "ph_003", "later_phase_ref": "ph_001"}
        ]
        ordered, errors = P.phase_topological_order(phases, cycle)
        self.assertTrue(errors)
        self.assertEqual(len(ordered), 0)

    def test_fail_closed_malformed_person_states(self) -> None:
        request, _ = base()
        cases = [
            ("phases_as_object", lambda c: c["person_states"].update(phases={})),
            ("facts_as_string", lambda c: c["person_states"].update(facts="x")),
            ("unit_phases_as_object", lambda c: c["person_states"].update(unit_phases={})),
            ("phase_as_string", lambda c: c["person_states"].update(phases=["x"])),
        ]
        for name, mutate in cases:
            with self.subTest(case=name):
                candidate = base()[1]
                mutate(candidate)
                try:
                    report = P.validate_person_state_candidate(request, candidate)
                except (TypeError, AttributeError) as exc:
                    self.fail(f"case {name} raised {type(exc).__name__}: {exc}")
                self.assertFalse(report["passed"], f"case {name} unexpectedly passed")


class AcceptanceTests(unittest.TestCase):
    def test_accept_emits_bound_artifact(self) -> None:
        request, candidate = base()
        producing_run = {"run_id": "r", "model": "m", "prompt_schema_version": "0.3"}
        artifact = P.accept_person_state_candidate(request, candidate, producing_run=producing_run)
        again = P.accept_person_state_candidate(request, candidate, producing_run=producing_run)
        self.assertEqual(artifact["schema"], "chronicle.chapter-artifact")
        self.assertEqual(artifact["version"], "0.3")
        self.assertEqual(artifact["artifact_sha256"], again["artifact_sha256"])
        self.assertEqual(artifact["person_states_sha256"], sha256_json(candidate["person_states"]))
        self.assertEqual(len(artifact["reading_units"]), 3)
        self.assertEqual(
            P._iter_schema_errors(P.artifact_v03_schema(), artifact, registry=P._registry()), []
        )
        keys = [entry["candidate_key"] for entry in artifact["person_state_candidates"]]
        kinds = [entry["kind"] for entry in artifact["person_state_candidates"]]
        self.assertEqual(kinds, sorted(kinds))
        self.assertEqual(len(set(keys)), len(keys))
        self.assertEqual(keys, [entry["candidate_key"] for entry in again["person_state_candidates"]])
        self.assertGreaterEqual(
            sum(1 for entry in artifact["person_state_candidates"] if entry["anchor_ids"]), 1
        )
        for entry in artifact["person_state_candidates"]:
            if entry["kind"] in ("phase", "phase_order", "fact", "continuity"):
                self.assertTrue(entry["anchor_ids"], f"{entry['kind']} {entry['item_ref']} has no anchors")

    def test_accept_rejects_failing_candidate_and_forged_report(self) -> None:
        request, _ = base()
        candidate = load("candidate-phase-cycle.json")
        run = {"run_id": "r", "model": "m", "prompt_schema_version": "0.3"}
        with self.assertRaises(PersistenceError):
            P.accept_person_state_candidate(request, candidate, producing_run=run)
        with self.assertRaises(PersistenceError):
            P.accept_person_state_candidate(
                request, candidate, producing_run=run, report={"passed": True, "errors": {}}
            )


class RemapTests(unittest.TestCase):
    def test_remap_preserves_origin_refs_and_hash(self) -> None:
        request, candidate = base()
        artifact = P.accept_person_state_candidate(
            request, candidate,
            producing_run={"run_id": "r", "model": "m", "prompt_schema_version": "0.3"},
        )
        manifests = P.remap_person_state_evidence(
            [artifact], {CHAPTER_ID: {"revision_id": "rev_assembled_007"}}
        )
        self.assertEqual(len(manifests), 1)
        manifest = manifests[0]
        self.assertEqual(manifest["origin_revision_id"], REVISION_ID)
        self.assertEqual(manifest["target_revision_id"], "rev_assembled_007")
        self.assertEqual(manifest["artifact_sha256"], artifact["artifact_sha256"])
        fact = manifest["facts"][0]
        self.assertEqual(fact["origin_chapter_id"], CHAPTER_ID)
        self.assertEqual(fact["origin_revision_id"], REVISION_ID)
        self.assertTrue(fact["anchor_ids"])
        self.assertEqual(fact["artifact_sha256"], artifact["artifact_sha256"])

    def test_remap_rejects_non_03_input(self) -> None:
        with self.assertRaises(PersistenceError):
            P.remap_person_state_evidence([{"schema": "chronicle.chapter-artifact", "version": "0.2"}], {})


class ProjectionTests(unittest.TestCase):
    def test_supported_current_is_clear(self) -> None:
        evidence, canonical, manifest = projection_inputs([evidence_fact("pf_001", phase_ref="ph_002")])
        result = P.compile_person_state_projection(evidence, {"pf_001": "supported"}, canonical, manifest)
        item = result["items"][0]
        self.assertEqual(item["certainty"], "clear")
        self.assertEqual(item["reason_codes"], [])
        self.assertTrue(item["current"])

    def test_prior_without_continuity_is_tenure_unproven(self) -> None:
        evidence, canonical, manifest = projection_inputs([evidence_fact("pf_001", phase_ref="ph_001")])
        result = P.compile_person_state_projection(evidence, {"pf_001": "supported"}, canonical, manifest)
        item = result["items"][0]
        self.assertEqual(item["certainty"], "uncertain")
        self.assertIn("tenure_unproven", item["reason_codes"])
        self.assertFalse(item["current"])

    def test_proven_continuity_covers_current(self) -> None:
        evidence, canonical, manifest = projection_inputs(
            [evidence_fact("pf_001", phase_ref="ph_001")],
            continuities=[{
                "fact_ref": "pf_001", "start_phase_ref": "ph_001", "end_phase_ref": "ph_003",
            }],
        )
        result = P.compile_person_state_projection(evidence, {"pf_001": "supported"}, canonical, manifest)
        item = result["items"][0]
        self.assertEqual(item["certainty"], "clear")
        self.assertTrue(item["current"])

    def test_future_title_is_not_leaked(self) -> None:
        evidence, canonical, manifest = projection_inputs([evidence_fact("pf_003", phase_ref="ph_003")])
        result = P.compile_person_state_projection(evidence, {"pf_003": "supported"}, canonical, manifest)
        self.assertEqual(result["items"], [])
        self.assertTrue(any(d["code"] == "phase_not_reached" for d in result["diagnostics"]))

    def test_recommendation_never_enters_current_identity(self) -> None:
        evidence, canonical, manifest = projection_inputs([
            evidence_fact("pf_rec", phase_ref="ph_002", qualification="recommendation", operation="attest")
        ])
        result = P.compile_person_state_projection(evidence, {"pf_rec": "supported"}, canonical, manifest)
        item = result["items"][0]
        self.assertEqual(item["certainty"], "uncertain")
        self.assertIn("attribution_uncertain", item["reason_codes"])
        self.assertFalse(item["current"])

    def test_rejected_fact_is_excluded(self) -> None:
        evidence, canonical, manifest = projection_inputs([evidence_fact("pf_001", phase_ref="ph_002")])
        result = P.compile_person_state_projection(evidence, {"pf_001": "rejected"}, canonical, manifest)
        self.assertEqual(result["items"], [])
        self.assertTrue(any(d["code"] == "rejected" for d in result["diagnostics"]))

    def test_disputed_fact_carries_source_disagreement(self) -> None:
        evidence, canonical, manifest = projection_inputs(
            [evidence_fact("pf_001", phase_ref="ph_002")],
            disagreements=[{"fact_refs": ["pf_001"], "topic": "同名事件"}],
        )
        result = P.compile_person_state_projection(evidence, {"pf_001": "disputed"}, canonical, manifest)
        item = result["items"][0]
        self.assertEqual(item["certainty"], "uncertain")
        self.assertIn("source_disagreement", item["reason_codes"])

    def test_missing_assessment_never_defaults_to_supported(self) -> None:
        evidence, canonical, manifest = projection_inputs([evidence_fact("pf_001", phase_ref="ph_002")])
        result = P.compile_person_state_projection(evidence, {}, canonical, manifest)
        item = result["items"][0]
        self.assertEqual(item["certainty"], "uncertain")
        self.assertIn("evidence_uncertain", item["reason_codes"])

    def test_unknown_person_is_diagnosed(self) -> None:
        evidence, _canonical, manifest = projection_inputs([evidence_fact("pf_001", phase_ref="ph_002")])
        result = P.compile_person_state_projection(evidence, {"pf_001": "supported"}, {}, manifest)
        self.assertEqual(result["items"], [])
        self.assertTrue(any(d["code"] == "unknown_person" for d in result["diagnostics"]))


class DisagreementIndexTests(unittest.TestCase):
    def test_index_filters_membership_and_is_deterministic(self) -> None:
        base_index = [{"topic": "A", "fact_refs": ["pf_001", "pf_002"], "phase_ids": ["ph_001"]}]
        reviewed = [{"topic": "B", "fact_refs": ["pf_003", "pf_004"], "reason_codes": ["source_disagreement"]}]
        membership = {"catalog_sha": CATALOG_SHA, "fact_refs": ["pf_001", "pf_002", "pf_003"]}
        first = P.compile_person_state_disagreements(base_index, reviewed, membership)
        second = P.compile_person_state_disagreements(base_index, reviewed, membership)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["fact_refs"], ["pf_001", "pf_002"])
        self.assertEqual([entry["disagreement_id"] for entry in first], sorted(
            entry["disagreement_id"] for entry in first
        ))

    def test_index_requires_catalog_sha(self) -> None:
        with self.assertRaises(PersistenceError):
            P.compile_person_state_disagreements([], [], {})


class ReviewScopeTests(unittest.TestCase):
    def test_omitted_scope_keeps_resolution(self) -> None:
        self.assertEqual(P.normalize_review_scope(None), "resolution")
        self.assertEqual(P.normalize_review_scope(""), "resolution")
        self.assertTrue(P.review_scope_covers(None, "resolution"))
        self.assertFalse(P.review_scope_covers(None, "person_state"))
        self.assertTrue(P.review_scope_covers("all", "person_state"))
        self.assertTrue(P.review_scope_covers("all", "resolution"))

    def test_omitted_scope_still_covers_narrative_facts_prose(self) -> None:
        # §5.1 regression: the legacy entry keeps comprehensive facts/prose;
        # adding person_state must not make narrative items disappear. This
        # must match person-state-types.ts reviewScopeCovers exactly.
        self.assertTrue(P.review_scope_covers(None, "narrative"))
        self.assertTrue(P.review_scope_covers("", "narrative"))
        self.assertTrue(P.review_scope_covers("resolution", "narrative"))
        self.assertTrue(P.review_scope_covers("all", "narrative"))

    def test_scope_coverage_matrix_matches_ts(self) -> None:
        expected = {
            None: {"resolution": True, "person_state": False, "narrative": True, "chapter_content": False},
            "resolution": {"resolution": True, "person_state": False, "narrative": True, "chapter_content": False},
            "person_state": {"resolution": False, "person_state": True, "narrative": False, "chapter_content": False},
            "chapter_content": {"resolution": False, "person_state": False, "narrative": False, "chapter_content": True},
            "all": {"resolution": True, "person_state": True, "narrative": True, "chapter_content": True},
        }
        for scope, surfaces in expected.items():
            for target, covered in surfaces.items():
                with self.subTest(scope=scope, target=target):
                    self.assertEqual(
                        P.review_scope_covers(scope, target), covered,
                        f"scope={scope!r} target={target!r}",
                    )

    def test_review_scope_schema_matches_current_queue_contract(self) -> None:
        from jsonschema import Draft202012Validator

        schema = P.person_state_schema()["$defs"]["review_scope"]
        self.assertEqual(schema["enum"], list(P.REVIEW_SCOPES))
        validator = Draft202012Validator(schema)
        for scope in ("resolution", "person_state", "chapter_content", "all"):
            with self.subTest(scope=scope):
                self.assertEqual(P.normalize_review_scope(scope), scope)
                self.assertEqual(list(validator.iter_errors(scope)), [])
        self.assertTrue(list(validator.iter_errors("everything")))

    def test_unknown_scope_and_link_kind_mixing_rejected(self) -> None:
        with self.assertRaises(PersistenceError):
            P.normalize_review_scope("narrative")
        with self.assertRaises(PersistenceError):
            P.assert_link_kind_scope("all", "same_person")
        P.assert_link_kind_scope("resolution", "same_person")
        P.assert_link_kind_scope("all", None)


class DtoContractTests(unittest.TestCase):
    EXAMPLES = {
        "unit-people-example.json": ("unit_people_page", "UnitPeoplePage"),
        "person-states-page-example.json": ("person_state_page", "PersonStatePage"),
        "state-evidence-page-example.json": ("state_evidence_page", "StateEvidencePage"),
        "place-state-example.json": ("place_state_page", "PlaceStatePage"),
        "review-package-example.json": ("review_package", "ReviewPackage"),
        "review-decision-example.json": ("assessment_overlay", "AssessmentOverlay"),
    }

    def test_examples_match_schema_and_budget(self) -> None:
        for name, (dto_name, _interface) in self.EXAMPLES.items():
            with self.subTest(example=name):
                value = load(name)
                self.assertEqual(P.person_state_response_errors(dto_name, value), [])

    def test_every_dto_has_a_typescript_mirror(self) -> None:
        source = PERSON_STATE_TYPES.read_text(encoding="utf-8")
        for name, (_dto_name, interface) in self.EXAMPLES.items():
            with self.subTest(example=name):
                self.assertIn(f"interface {interface}", source)
                for key in load(name).keys():
                    self.assertIn(key, source, f"{name} field {key!r} missing from person-state-types.ts")
        for extra in (
            "PersonStateLocator",
            "StateItem",
            "StateChange",
            "PersonSummary",
            "ReviewCandidate",
            "isPersonStateLocator",
            "isCertainty",
            "STATE_DIMENSIONS",
            "REASON_CODES",
            "normalizeReviewScope",
        ):
            self.assertIn(extra, source)

    def test_review_candidate_and_item_examples(self) -> None:
        package = load("review-package-example.json")
        candidate = package["candidates"][0]
        self.assertEqual(P.validate_person_state_dto("review_candidate", candidate), [])
        people = load("unit-people-example.json")
        item = people["people"][0]["identities"][0]
        self.assertEqual(P.validate_person_state_dto("state_item", item), [])

    def test_item_id_and_candidate_key_are_stable(self) -> None:
        first = P.item_id_for(
            chapter_id=CHAPTER_ID, fact_ref="pf_001", dimension="office",
            phase_id="ph_001", person_ref="ent_002", operation="start",
        )
        second = P.item_id_for(
            chapter_id=CHAPTER_ID, fact_ref="pf_001", dimension="office",
            phase_id="ph_001", person_ref="ent_002", operation="start",
        )
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("psi_"))
        key = P.candidate_key_for(kind="fact", chapter_id=CHAPTER_ID, item_ref="pf_001", anchor_ids=["a", "b"])
        key_again = P.candidate_key_for(
            kind="fact", chapter_id=CHAPTER_ID, item_ref="pf_001", anchor_ids=["b", "a"]
        )
        self.assertEqual(key, key_again)
        self.assertTrue(key.startswith("psc_"))

    def test_plan_fingerprint_is_order_insensitive(self) -> None:
        first = P.person_state_plan_fingerprint(
            accepted_artifact_hashes=["a", "b"], assembled_hash="x",
            evidence_manifests_sha256="m" * 64,
            resolution_hashes=["r2", "r1"], base_catalog_sha=CATALOG_SHA,
            candidate_keys=["k2", "k1"],
        )
        second = P.person_state_plan_fingerprint(
            accepted_artifact_hashes=["b", "a"], assembled_hash="x",
            evidence_manifests_sha256="m" * 64,
            resolution_hashes=["r1", "r2"], base_catalog_sha=CATALOG_SHA,
            candidate_keys=["k1", "k2"],
        )
        self.assertEqual(first, second)

    def test_plan_fingerprint_covers_evidence_manifest_digest(self) -> None:
        baseline = P.person_state_plan_fingerprint(
            accepted_artifact_hashes=["a"], assembled_hash="x",
            evidence_manifests_sha256="m" * 64,
            resolution_hashes=["r1"], base_catalog_sha=CATALOG_SHA,
            candidate_keys=["k1"],
        )
        changed = P.person_state_plan_fingerprint(
            accepted_artifact_hashes=["a"], assembled_hash="x",
            evidence_manifests_sha256="n" * 64,
            resolution_hashes=["r1"], base_catalog_sha=CATALOG_SHA,
            candidate_keys=["k1"],
        )
        self.assertNotEqual(baseline, changed)


if __name__ == "__main__":
    unittest.main()
