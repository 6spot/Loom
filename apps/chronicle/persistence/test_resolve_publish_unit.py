"""Unit tests for Chronicle C1-T8 resolution/review/publication (no PostgreSQL).

Covers the deterministic, C0-reusing core: cross-source candidate
building against a corpus, conservative all-uncertain initial
decisions with full provenance, review-payload validation, decision
application (including stale-decision rejection and dismissed-as-
uncertain), canonical publication boundaries (merge, UUID reuse,
negative constraints, fail-closed conflicts), and byte-deterministic
reruns. The durable worker path is covered by
``apps/chronicle/worker/test_resolve_publish_postgres.py``.
"""

from __future__ import annotations

import copy
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
for path in (str(HERE),):
    if path not in sys.path:
        sys.path.insert(0, path)

import resolve_publish as R  # noqa: E402
import person_state_contract as P  # noqa: E402
from common import PersistenceError, canonical_json_bytes  # noqa: E402


def _source(title: str) -> dict:
    return {
        "temp_id": "src_001",
        "kind": "source",
        "source_type": "book",
        "title": title,
        "author": "陳壽",
        "language": "lzh",
    }


def _entity(temp_id: str, name: str, etype: str = "person") -> dict:
    return {
        "temp_id": temp_id,
        "kind": "entity",
        "type": etype,
        "canonical_name": name,
        "aliases": [],
        "mentions": [{"text": name}],
    }


def _event(
    temp_id: str,
    title: str,
    etype: str = "death",
    participants: list[str] | None = None,
    time: dict | None = None,
) -> dict:
    return {
        "temp_id": temp_id,
        "kind": "event",
        "type": etype,
        "title": title,
        "time": time,
        "participants": [
            {"entity_ref": ref, "role": "subject"} for ref in (participants or [])
        ],
        "places": [],
    }


def _bundle(title: str, entities: list[dict], events: list[dict]) -> dict:
    return {
        "schema_version": "0.1",
        "source": _source(title),
        "entities": entities,
        "events": events,
        "claims": [],
        "warnings": [],
    }


def _year(year: int) -> dict:
    return {
        "source_calendar": {"era": "建安", "era_year": year - 195},
        "normalized": {"year": year},
    }


class BundleLabelTests(unittest.TestCase):
    def test_label_is_deterministic(self) -> None:
        revision = uuid.uuid4()
        self.assertEqual(
            R.new_bundle_label(revision), R.new_bundle_label(str(revision))
        )
        self.assertTrue(R.new_bundle_label(revision).startswith("c1rev-"))

    def test_label_rejects_non_uuid(self) -> None:
        with self.assertRaises(PersistenceError):
            R.new_bundle_label("not-a-uuid")


class InitialResolutionTests(unittest.TestCase):
    def test_disjoint_bundles_yield_no_artifacts(self) -> None:
        left = _bundle("左傳（節選）", [_entity("ent_001", "曹操")], [])
        right = _bundle("史記（節選）", [_entity("ent_001", "劉邦")], [])
        self.assertEqual(
            R.build_initial_resolutions(
                new_bundle=right, new_label="new", corpus={"old": left}
            ),
            [],
        )

    def test_shared_name_blocks_exact_candidate_as_uncertain(self) -> None:
        left = _bundle("武帝紀", [_entity("ent_001", "曹操")], [])
        right = _bundle("吳主傳", [_entity("ent_007", "曹操")], [])
        resolutions = R.build_initial_resolutions(
            new_bundle=right, new_label="new", corpus={"old": left}
        )
        self.assertEqual(len(resolutions), 1)
        resolution = resolutions[0]
        self.assertEqual(resolution["schema"], "chronicle.resolution-links")
        self.assertEqual(
            resolution["left_bundle"],
            {"label": "old", "source_ref": "src_001", "source_title": "武帝紀"},
        )
        self.assertEqual(
            resolution["right_bundle"],
            {"label": "new", "source_ref": "src_001", "source_title": "吳主傳"},
        )
        self.assertEqual(len(resolution["entity_links"]), 1)
        link = resolution["entity_links"][0]
        self.assertEqual(link["left"], {"bundle": "old", "ref": "ent_001"})
        self.assertEqual(link["right"], {"bundle": "new", "ref": "ent_007"})
        # Conservative: a shared name alone never proves identity.
        self.assertEqual(link["decision"], "uncertain")
        self.assertEqual(link["confidence"], 0.5)
        self.assertTrue(link["rationale"])
        self.assertTrue(link["signals"])
        self.assertEqual(
            resolution["warnings"],
            [
                {
                    "type": "unresolved_resolution",
                    "message": "Resolution candidate ec_001 remains uncertain.",
                    "refs": ["ec_001"],
                }
            ],
        )

    def test_event_candidate_uses_c0_time_and_participant_blocking(self) -> None:
        left = _bundle(
            "武帝紀",
            [_entity("ent_001", "曹操")],
            [_event("evt_001", "曹操之死", participants=["ent_001"], time=_year(220))],
        )
        right = _bundle(
            "吳主傳",
            [_entity("ent_003", "曹操")],
            [_event("evt_009", "魏武之薨", participants=["ent_003"], time=_year(220))],
        )
        resolutions = R.build_initial_resolutions(
            new_bundle=right, new_label="new", corpus={"old": left}
        )
        kinds = {
            link["candidate_id"]: link["decision"]
            for resolution in resolutions
            for link in resolution["event_links"]
        }
        self.assertTrue(kinds)
        self.assertTrue(all(decision == "uncertain" for decision in kinds.values()))

    def test_conflicting_time_blocks_no_event_candidate(self) -> None:
        left = _bundle(
            "武帝紀",
            [_entity("ent_001", "曹操")],
            [_event("evt_001", "曹操之死", participants=["ent_001"], time=_year(220))],
        )
        right = _bundle(
            "吳主傳",
            [_entity("ent_003", "曹操")],
            [_event("evt_009", "曹操之死", participants=["ent_003"], time=_year(221))],
        )
        resolutions = R.build_initial_resolutions(
            new_bundle=right, new_label="new", corpus={"old": left}
        )
        self.assertEqual(
            [len(item.get("event_links") or []) for item in resolutions], [0]
            if resolutions
            else []
        )
        # The entity pair still blocks; only the event pair is excluded.
        self.assertTrue(resolutions)
        self.assertEqual(len(resolutions[0]["entity_links"]), 1)

    def test_own_label_is_never_paired_with_itself(self) -> None:
        bundle = _bundle("武帝紀", [_entity("ent_001", "曹操")], [])
        self.assertEqual(
            R.build_initial_resolutions(
                new_bundle=bundle, new_label="old", corpus={"old": bundle}
            ),
            [],
        )

    def test_pairs_visit_corpus_in_label_order(self) -> None:
        new = _bundle("新書", [_entity("ent_001", "曹操")], [])
        corpus = {
            "b-book": _bundle("乙書", [_entity("ent_001", "曹操")], []),
            "a-book": _bundle("甲書", [_entity("ent_001", "曹操")], []),
        }
        resolutions = R.build_initial_resolutions(
            new_bundle=new, new_label="new", corpus=corpus
        )
        self.assertEqual(
            [item["left_bundle"]["label"] for item in resolutions],
            ["a-book", "b-book"],
        )

    def test_rerun_is_byte_identical(self) -> None:
        left = _bundle("武帝紀", [_entity("ent_001", "曹操")], [])
        right = _bundle("吳主傳", [_entity("ent_007", "曹操")], [])
        first = R.build_initial_resolutions(
            new_bundle=right, new_label="new", corpus={"old": left}
        )
        second = R.build_initial_resolutions(
            new_bundle=right, new_label="new", corpus={"old": left}
        )
        self.assertEqual(
            canonical_json_bytes(first), canonical_json_bytes(second)
        )


class ReviewPayloadTests(unittest.TestCase):
    def test_entity_payload_carries_provenance_and_vocab(self) -> None:
        payload = R.review_payload(
            resolution_sha="r" * 64,
            candidate={
                "candidate_id": "ec_001",
                "left": {"bundle": "old", "ref": "ent_001"},
                "right": {"bundle": "new", "ref": "ent_007"},
                "decision": "uncertain",
                "signals": ["exact canonical surface: 曹操"],
            },
            link_kind="entity",
        )
        self.assertEqual(payload["scope"], "resolution")
        self.assertEqual(payload["link_kind"], "entity")
        self.assertEqual(payload["left"], {"bundle": "old", "ref": "ent_001"})
        self.assertTrue(payload["blocking"])
        self.assertEqual(
            payload["allowed_decisions"], ["same_entity", "not_same", "uncertain"]
        )
        self.assertIsNone(payload["decision"])

    def test_event_payload_uses_event_vocab(self) -> None:
        payload = R.review_payload(
            resolution_sha="r" * 64,
            candidate={
                "candidate_id": "vc_001",
                "left": {"bundle": "old", "ref": "evt_001"},
                "right": {"bundle": "new", "ref": "evt_009"},
                "decision": "uncertain",
                "signals": [],
            },
            link_kind="event",
        )
        self.assertEqual(
            payload["allowed_decisions"],
            ["same_occurrence", "related_occurrence", "not_same", "uncertain"],
        )

    def test_payload_rejects_missing_provenance(self) -> None:
        with self.assertRaises(PersistenceError):
            R.review_payload(
                resolution_sha="r" * 64,
                candidate={"candidate_id": "ec_001", "left": {}, "right": {}},
                link_kind="entity",
            )
        with self.assertRaises(PersistenceError):
            R.review_payload(
                resolution_sha="r" * 64,
                candidate={"candidate_id": "ec_001"},
                link_kind="bogus",
            )


def _decisions(mapping: dict[str, str]) -> dict[str, dict[str, Any]]:
    return {
        key: {"decision": decision, "confidence": 0.9, "rationale": "human review"}
        for key, decision in mapping.items()
    }


class FinalResolutionTests(unittest.TestCase):
    def _initial(self) -> list[dict]:
        left = _bundle(
            "武帝紀",
            [_entity("ent_001", "曹操")],
            [_event("evt_001", "曹操之死", participants=["ent_001"], time=_year(220))],
        )
        right = _bundle(
            "吳主傳",
            [_entity("ent_007", "曹操")],
            [_event("evt_009", "魏武之薨", participants=["ent_007"], time=_year(220))],
        )
        return R.build_initial_resolutions(
            new_bundle=right, new_label="new", corpus={"old": left}
        )

    def test_human_decisions_apply_without_touching_provenance(self) -> None:
        initial = self._initial()
        sha = R.initial_artifact_sha(initial[0])
        final = R.build_final_resolutions(
            initial,
            _decisions({f"{sha}:ec_001": "same_entity", f"{sha}:vc_001": "uncertain"}),
        )
        entity = final[0]["entity_links"][0]
        self.assertEqual(entity["decision"], "same_entity")
        self.assertEqual(entity["confidence"], 0.9)
        self.assertEqual(entity["rationale"], "human review")
        self.assertEqual(entity["left"], {"bundle": "old", "ref": "ent_001"})
        self.assertEqual(entity["signals"], initial[0]["entity_links"][0]["signals"])
        event = final[0]["event_links"][0]
        self.assertEqual(event["decision"], "uncertain")
        # Only the remaining uncertain link keeps a warning.
        self.assertEqual(
            [warning["refs"] for warning in final[0]["warnings"]], [["vc_001"]]
        )

    def test_missing_decision_fails_closed_when_required(self) -> None:
        initial = self._initial()
        with self.assertRaises(PersistenceError):
            R.build_final_resolutions(initial, {})

    def test_missing_decision_stays_uncertain_when_allowed(self) -> None:
        initial = self._initial()
        final = R.build_final_resolutions(initial, {}, require_complete=False)
        self.assertEqual(final[0]["entity_links"][0]["decision"], "uncertain")

    def test_stale_decisions_do_not_apply(self) -> None:
        initial = self._initial()
        with self.assertRaises(PersistenceError):
            R.build_final_resolutions(
                initial, _decisions({"0" * 64 + ":ec_001": "same_entity"})
            )

    def test_invalid_decision_is_rejected(self) -> None:
        initial = self._initial()
        sha = R.initial_artifact_sha(initial[0])
        with self.assertRaises(PersistenceError):
            R.build_final_resolutions(
                initial,
                _decisions(
                    {
                        f"{sha}:ec_001": "same_occurrence",
                        f"{sha}:vc_001": "uncertain",
                    }
                ),
            )

    def test_dismissed_style_entry_finalizes_as_uncertain(self) -> None:
        """A collected dismissal (explicit uncertain) satisfies completeness."""
        initial = self._initial()
        sha = R.initial_artifact_sha(initial[0])
        decisions = {
            f"{sha}:ec_001": {
                "decision": "uncertain",
                "confidence": 0.5,
                "rationale": "review dismissed; kept distinct",
                "dismissed": True,
            },
            f"{sha}:vc_001": {
                "decision": "uncertain",
                "confidence": 0.5,
                "rationale": "review dismissed; kept distinct",
                "dismissed": True,
            },
        }
        final = R.build_final_resolutions(initial, decisions)
        self.assertEqual(final[0]["entity_links"][0]["decision"], "uncertain")
        self.assertIn("dismissed", final[0]["entity_links"][0]["rationale"])

    def test_final_rerun_is_byte_identical(self) -> None:
        initial = self._initial()
        sha = R.initial_artifact_sha(initial[0])
        decisions = _decisions(
            {f"{sha}:ec_001": "not_same", f"{sha}:vc_001": "related_occurrence"}
        )
        self.assertEqual(
            canonical_json_bytes(R.build_final_resolutions(initial, decisions)),
            canonical_json_bytes(R.build_final_resolutions(initial, decisions)),
        )
        # Inputs are never mutated by finalization.
        self.assertEqual(initial[0]["entity_links"][0]["decision"], "uncertain")


class PersonStateManifestPlaceTests(unittest.TestCase):
    def test_manifest_carries_canonical_place_items_and_evidence(self) -> None:
        revision_id = uuid.uuid4()
        publication_id = str(uuid.uuid4())
        place = P.example_place_state_item(
            place_id="place_ref",
            name="荊州",
            dimension="administration",
            value="荊州",
            controller="ent_controller",
            certainty="clear",
            phase_ids=["ph_001"],
            source_facts=[
                {
                    "chapter_publication_id": publication_id,
                    "chapter_id": "ch_001",
                    "revision_id": str(revision_id),
                    "fact_ref": "pf_001",
                    "claim_refs": [],
                    "phase_id": "ph_001",
                }
            ],
            chapter_id="ch_001",
            fact_ref="pf_001",
            person_ref="place_ref",
            current=True,
        )
        descriptor = P.example_evidence_descriptor(
            descriptor_id="desc_place",
            source_publication_id=publication_id,
            anchor_id="anc_0123456789abcdef",
            quote="荊州刺史",
            source_title="吳主傳",
            phase_id="ph_001",
        )
        projection = {
            "units": [
                {
                    "unit_id": "ru_001",
                    "ordinal": 0,
                    "block_id": "block_001",
                    "chapter_id": "ch_001",
                    "publication_id": publication_id,
                    "context_entities": [
                        {
                            "entity_ref": "place_ref",
                            "canonical_id": "ent_place",
                            "kind": "place",
                            "name": "荊州",
                        }
                    ],
                }
            ]
        }
        catalog = {
            "canonical_entities": [
                {
                    "canonical_id": "ent_place",
                    "canonical_name": "荊州",
                    "representations": [{"bundle": "bundle", "ref": "place_ref"}],
                }
            ],
            "canonical_events": [],
        }
        compiled = {
            "people": {},
            "places": [place],
            "evidence": [{"item_id": place["item_id"], "descriptors": [descriptor]}],
        }
        with mock.patch.object(
            R.person_state_projection,
            "compile_person_state_projection",
            return_value=compiled,
        ):
            manifest = R.build_person_state_manifest(
                projection=projection,
                catalog=catalog,
                bundle_label="bundle",
                stream_id=str(uuid.uuid4()),
                revision_id=revision_id,
                chapter_publication_ids=[publication_id],
                publication_by_chapter={"ch_001": publication_id},
                evidence={
                    "unit_phases": [
                        {"block_id": "block_001", "mode": "single", "phase_refs": ["ph_001"]}
                    ],
                    "phases": [{"phase_id": "ph_001", "label": "初"}],
                },
                assessments={},
                assessment_hashes=[],
            )

        unit = manifest["units"][0]
        self.assertEqual("ent_place", unit["places"][0]["place_id"])
        self.assertEqual(place["item_id"], unit["places"][0]["item_id"])
        self.assertEqual(place["item_id"], unit["place_evidence"][0]["item_id"])
        self.assertEqual(1, manifest["manifest"]["counts"]["places"])

    def test_manifest_rejects_place_item_bound_to_non_place_context(self) -> None:
        revision_id = uuid.uuid4()
        publication_id = str(uuid.uuid4())
        place = P.example_place_state_item(
            place_id="place_ref",
            name="荊州",
            dimension="administration",
            value="荊州",
            controller="ent_controller",
            certainty="clear",
            phase_ids=["ph_001"],
            source_facts=[
                {
                    "chapter_publication_id": publication_id,
                    "chapter_id": "ch_001",
                    "revision_id": str(revision_id),
                    "fact_ref": "pf_002",
                    "claim_refs": [],
                    "phase_id": "ph_001",
                }
            ],
            chapter_id="ch_001",
            fact_ref="pf_002",
            person_ref="place_ref",
            current=True,
        )
        projection = {
            "units": [
                {
                    "unit_id": "ru_001",
                    "ordinal": 0,
                    "block_id": "block_001",
                    "chapter_id": "ch_001",
                    "publication_id": publication_id,
                    "context_entities": [
                        {
                            "entity_ref": "place_ref",
                            "canonical_id": "ent_polity",
                            "kind": "polity",
                            "name": "荊州政權",
                        }
                    ],
                }
            ]
        }
        catalog = {
            "canonical_entities": [
                {
                    "canonical_id": "ent_polity",
                    "canonical_name": "荊州政權",
                    "representations": [{"bundle": "bundle", "ref": "place_ref"}],
                }
            ],
            "canonical_events": [],
        }
        compiled = {"people": {}, "places": [place], "evidence": []}
        with mock.patch.object(
            R.person_state_projection,
            "compile_person_state_projection",
            return_value=compiled,
        ):
            with self.assertRaisesRegex(PersistenceError, "without a place context entity"):
                R.build_person_state_manifest(
                    projection=projection,
                    catalog=catalog,
                    bundle_label="bundle",
                    stream_id=str(uuid.uuid4()),
                    revision_id=revision_id,
                    chapter_publication_ids=[publication_id],
                    publication_by_chapter={"ch_001": publication_id},
                    evidence={
                        "unit_phases": [
                            {
                                "block_id": "block_001",
                                "mode": "single",
                                "phase_refs": ["ph_001"],
                            }
                        ],
                        "phases": [{"phase_id": "ph_001", "label": "初"}],
                    },
                    assessments={},
                    assessment_hashes=[],
                )


class PublicationTests(unittest.TestCase):
    def _world(self) -> tuple[dict, dict, list]:
        left = _bundle(
            "武帝紀",
            [_entity("ent_001", "曹操")],
            [_event("evt_001", "曹操之死", participants=["ent_001"], time=_year(220))],
        )
        right = _bundle(
            "吳主傳",
            [_entity("ent_007", "曹操")],
            [_event("evt_009", "魏武之薨", participants=["ent_007"], time=_year(220))],
        )
        initial = R.build_initial_resolutions(
            new_bundle=right, new_label="new", corpus={"old": left}
        )
        return {"old": left, "new": right}, initial

    def test_accepted_same_link_merges_and_uncertain_stays_distinct(self) -> None:
        bundles, initial = self._world()
        sha = R.initial_artifact_sha(initial[0])
        final = R.build_final_resolutions(
            initial,
            _decisions({f"{sha}:ec_001": "same_entity", f"{sha}:vc_001": "uncertain"}),
        )
        catalog, report = R.publish_with_decisions(
            bundles=bundles, resolutions=final, existing_catalog=None
        )
        self.assertEqual(len(catalog["canonical_entities"]), 1)
        self.assertEqual(
            catalog["canonical_entities"][0]["representations"],
            [
                {"bundle": "new", "ref": "ent_007"},
                {"bundle": "old", "ref": "ent_001"},
            ],
        )
        # The uncertain event pair publishes as two distinct occurrences.
        self.assertEqual(len(catalog["canonical_events"]), 2)
        self.assertEqual(catalog["event_relations"], [])
        self.assertEqual(
            report["decisions"],
            {"entities": {"same_entity": 1}, "events": {"uncertain": 1}},
        )
        self.assertIn("catalog_sha256", report)

    def test_existing_catalog_uuids_are_reused(self) -> None:
        bundles, initial = self._world()
        first, _ = R.publish_with_decisions(
            bundles={"old": bundles["old"]},
            resolutions=[],
            existing_catalog=None,
        )
        old_entity_id = first["canonical_entities"][0]["canonical_id"]
        sha = R.initial_artifact_sha(initial[0])
        final = R.build_final_resolutions(
            initial,
            _decisions({f"{sha}:ec_001": "same_entity", f"{sha}:vc_001": "uncertain"}),
        )
        second, _ = R.publish_with_decisions(
            bundles=bundles, resolutions=final, existing_catalog=first
        )
        attached = [
            record
            for record in second["canonical_entities"]
            if record["canonical_id"] == old_entity_id
        ]
        self.assertEqual(len(attached), 1)
        self.assertEqual(
            attached[0]["representations"],
            [
                {"bundle": "new", "ref": "ent_007"},
                {"bundle": "old", "ref": "ent_001"},
            ],
        )

    def test_contradictory_links_fail_closed(self) -> None:
        bundles = {
            "old": _bundle("武帝紀", [_entity("ent_001", "曹操")], []),
            "new": _bundle(
                "吳主傳",
                [_entity("ent_007", "曹操"), _entity("ent_008", "曹操")],
                [],
            ),
        }
        initial = R.build_initial_resolutions(
            new_bundle=bundles["new"], new_label="new", corpus={"old": bundles["old"]}
        )
        self.assertEqual(len(initial[0]["entity_links"]), 2)
        sha = R.initial_artifact_sha(initial[0])
        by_pair = {
            (link["left"]["ref"], link["right"]["ref"]): link["candidate_id"]
            for link in initial[0]["entity_links"]
        }
        final = R.build_final_resolutions(
            initial,
            _decisions(
                {
                    f"{sha}:{by_pair[('ent_001', 'ent_007')]}": "same_entity",
                    f"{sha}:{by_pair[('ent_001', 'ent_008')]}": "same_entity",
                }
            ),
        )
        # Both same-links transitively place the two new-bundle
        # representations under one identity; a not_same between them
        # must fail rather than silently split or merge.
        poisoned = copy.deepcopy(final)
        poisoned[0]["entity_links"].append(
            {
                "candidate_id": "ec_999",
                "left": {"bundle": "new", "ref": "ent_007"},
                "right": {"bundle": "new", "ref": "ent_008"},
                "decision": "not_same",
                "confidence": 1.0,
                "rationale": "contradiction probe",
                "signals": [],
            }
        )
        from publication_v0 import PublicationConflict

        with self.assertRaises(PublicationConflict):
            R.publish_with_decisions(
                bundles=bundles, resolutions=poisoned, existing_catalog=None
            )

    def test_related_occurrence_becomes_relation_not_merge(self) -> None:
        bundles, initial = self._world()
        sha = R.initial_artifact_sha(initial[0])
        final = R.build_final_resolutions(
            initial,
            _decisions(
                {f"{sha}:ec_001": "uncertain", f"{sha}:vc_001": "related_occurrence"}
            ),
        )
        catalog, _ = R.publish_with_decisions(
            bundles=bundles, resolutions=final, existing_catalog=None
        )
        self.assertEqual(len(catalog["canonical_events"]), 2)
        self.assertEqual(len(catalog["event_relations"]), 1)
        relation = catalog["event_relations"][0]
        self.assertEqual(relation["type"], "related_occurrence")
        self.assertNotEqual(
            relation["left_canonical_event_id"],
            relation["right_canonical_event_id"],
        )

    def test_collapsing_existing_ids_fails_closed(self) -> None:
        bundles, initial = self._world()
        first, _ = R.publish_with_decisions(
            bundles=bundles, resolutions=[], existing_catalog=None
        )
        self.assertEqual(len(first["canonical_entities"]), 2)
        sha = R.initial_artifact_sha(initial[0])
        final = R.build_final_resolutions(
            initial,
            _decisions({f"{sha}:ec_001": "same_entity", f"{sha}:vc_001": "uncertain"}),
        )
        from publication_v0 import PublicationConflict

        # Both representations already own distinct canonical UUIDs:
        # no silent collapse is allowed.
        with self.assertRaises(PublicationConflict):
            R.publish_with_decisions(
                bundles=bundles, resolutions=final, existing_catalog=first
            )


def _chapter_bundle() -> tuple[dict, dict[str, str]]:
    """One assembled bundle with 曹操 in chapters A/B and 刘备 in B."""
    bundle = _bundle(
        "三國志（兩章合裝）",
        [
            _entity("ent_000001", "曹操"),
            _entity("ent_001001", "曹操"),
            _entity("ent_001002", "劉備"),
        ],
        [],
    )
    chapters = {
        "ent_000001": "ch_A",
        "ent_001001": "ch_B",
        "ent_001002": "ch_B",
    }
    return bundle, chapters


def _chapter_index() -> dict[str, int]:
    """Assembly plan chapter order for the `_chapter_bundle` fixture."""
    return {"ch_A": 0, "ch_B": 1}


def _chapter_uuid7(n: int) -> str:
    return f"019535d9-3df7-7{n:03x}-8000-00000000000{n:x}"


class WithinBundleInitialTests(unittest.TestCase):
    def test_cross_chapter_same_name_blocks_but_same_chapter_does_not(self) -> None:
        bundle, chapters = _chapter_bundle()
        initial = R.build_within_bundle_initial_resolution(
            bundle=bundle,
            bundle_label="bund",
            chapter_by_ref=chapters,
            chapter_index_by_id=_chapter_index(),
        )
        assert initial is not None
        self.assertEqual(initial["version"], "0.2")
        self.assertEqual(initial["scope"], "within_revision")
        self.assertEqual(initial["left_bundle"]["label"], "bund")
        self.assertEqual(initial["right_bundle"]["label"], "bund")
        pairs = {
            (link["left"]["ref"], link["right"]["ref"])
            for link in initial["entity_links"]
        }
        # Only the A/B 曹操 pair blocks; same-chapter B/B never pairs.
        self.assertEqual(pairs, {("ent_000001", "ent_001001")})
        self.assertTrue(
            all(link["decision"] == "uncertain" for link in initial["entity_links"])
        )

    def test_same_chapter_pairs_never_block(self) -> None:
        bundle, _ = _chapter_bundle()
        # All same chapter: no candidates at all, hence no artifacts.
        self.assertEqual(
            R.build_chapter_initial_resolutions(
                bundle=bundle,
                bundle_label="bund",
                chapter_by_ref={
                    "ent_000001": "ch_A",
                    "ent_001001": "ch_A",
                    "ent_001002": "ch_A",
                },
                chapter_index_by_id={"ch_A": 0},
            ),
            [],
        )

    def test_cross_source_builder_still_forbids_same_bundle(self) -> None:
        import resolution_v0

        bundle, _ = _chapter_bundle()
        with self.assertRaises(resolution_v0.ResolutionV0Error):
            resolution_v0.build_cross_source_candidate_set_v02(
                bundle, "bund", bundle, "bund"
            )

    def test_self_link_initial_is_rejected(self) -> None:
        import resolution_store

        bundle, chapters = _chapter_bundle()
        initial = R.build_within_bundle_initial_resolution(
            bundle=bundle,
            bundle_label="bund",
            chapter_by_ref=chapters,
            chapter_index_by_id=_chapter_index(),
        )
        assert initial is not None
        poisoned = copy.deepcopy(initial)
        poisoned["entity_links"].append(
            {
                "candidate_id": "ec_999",
                "left": {"bundle": "bund", "ref": "ent_000001"},
                "right": {"bundle": "bund", "ref": "ent_000001"},
                "decision": "uncertain",
                "confidence": 0.5,
                "rationale": "self probe",
                "signals": [],
            }
        )
        with self.assertRaises(PersistenceError):
            resolution_store.validate_resolution_envelope(poisoned)
        # The publisher fails closed on the same self-link (wrapped boundary).
        with self.assertRaises(PersistenceError):
            R.publish_with_decisions(
                bundles={"bund": bundle},
                resolutions=[poisoned],
                existing_catalog=None,
            )


class ChapterReviewPlanTests(unittest.TestCase):
    def _plan_world(self):
        bundle, chapters = _chapter_bundle()
        published = _bundle("舊刊", [_entity("ent_900", "曹操")], [])
        corpus = {"old": published}
        initials = R.build_chapter_initial_resolutions(
            bundle=bundle,
            bundle_label="bund",
            chapter_by_ref=chapters,
            chapter_index_by_id=_chapter_index(),
            corpus=corpus,
        )
        catalog, _ = R.publish_with_decisions(
            bundles={"old": published}, resolutions=[], existing_catalog=None
        )
        return bundle, chapters, published, initials, catalog

    def test_mixed_pair_and_batch_cover_each_candidate_once(self) -> None:
        bundle, chapters, _published, initials, catalog = self._plan_world()
        scopes = sorted(item.get("scope") for item in initials)
        self.assertEqual(scopes, ["cross_source", "within_revision"])
        job_id, revision_id = uuid.uuid4(), uuid.uuid4()
        from common import sha256_json

        assembled_sha = sha256_json(bundle)
        base_sha = sha256_json(catalog)
        plan = R.create_chapter_review_plan(
            job_id=job_id,
            revision_id=revision_id,
            assembled_bundle_sha256=assembled_sha,
            base_catalog_sha256=base_sha,
            initial_resolutions=initials,
            catalog=catalog,
            chapter_by_ref=chapters,
        )
        self.assertEqual(plan["version"], "c2r1-review-plan-v1")
        self.assertEqual(len(plan["pair_payloads"]), 1)
        self.assertEqual(plan["pair_payloads"][0]["review_mode"], "chapter_pair")
        self.assertEqual(len(plan["batch_payloads"]), 1)
        self.assertEqual(plan["batch_payloads"][0]["review_mode"], "published_batch")
        self.assertEqual(
            plan["pair_payloads"][0]["allowed_decisions"],
            ["same_entity", "not_same", "uncertain"],
        )
        # Exact-once coverage across both modes.
        from review_subjects import _payload_candidate_keys

        covered = sorted(
            key
            for payload in plan["pair_payloads"] + plan["batch_payloads"]
            for key in _payload_candidate_keys(payload)
        )
        from review_subjects import _candidate_members

        expected = sorted(
            item["candidate_key"]
            for item in _candidate_members(initials)
        )
        self.assertEqual(covered, expected)
        # Fingerprint restores exactly; tampered inputs fail closed.
        fingerprint = R.validate_chapter_review_plan(
            plan,
            initials,
            job_id=job_id,
            revision_id=revision_id,
            assembled_bundle_sha256=assembled_sha,
            base_catalog_sha256=base_sha,
        )
        self.assertEqual(fingerprint, plan["plan_fingerprint"])
        from common import PersistenceConflict

        with self.assertRaises(PersistenceConflict):
            R.validate_chapter_review_plan(
                plan,
                initials,
                job_id=job_id,
                revision_id=revision_id,
                assembled_bundle_sha256="0" * 64,
                base_catalog_sha256=base_sha,
            )
        # Reordered inputs yield the same fingerprint (no re-materialization).
        plan2 = R.create_chapter_review_plan(
            job_id=job_id,
            revision_id=revision_id,
            assembled_bundle_sha256=assembled_sha,
            base_catalog_sha256=base_sha,
            initial_resolutions=list(reversed(initials)),
            catalog=catalog,
            chapter_by_ref=chapters,
        )
        self.assertEqual(plan2["plan_fingerprint"], plan["plan_fingerprint"])

    def test_wrong_mode_group_or_duplicate_candidates_rejected(self) -> None:
        import review_subjects
        from common import PersistenceConflict

        bundle, chapters, _published, initials, catalog = self._plan_world()
        job_id, revision_id = uuid.uuid4(), uuid.uuid4()
        from common import sha256_json

        plan = R.create_chapter_review_plan(
            job_id=job_id,
            revision_id=revision_id,
            assembled_bundle_sha256=sha256_json(bundle),
            base_catalog_sha256=sha256_json(catalog),
            initial_resolutions=initials,
            catalog=catalog,
            chapter_by_ref=chapters,
        )
        pair_payload = plan["pair_payloads"][0]
        # chapter_pair accepts no group overrides.
        with self.assertRaises(PersistenceError):
            review_subjects.normalize_group_decisions(
                pair_payload,
                [
                    {
                        "review_group_id": "rg_missing",
                        "decision": "not_same",
                        "confidence": 0.9,
                        "rationale": "例外探針",
                    }
                ],
            )
        # Unknown batch group override fails closed.
        batch_payload = copy.deepcopy(plan["batch_payloads"][0])
        batch_payload["decision"] = {
            "decision": "same_entity",
            "confidence": 0.9,
            "rationale": "默認判斷",
            "group_decisions": [
                {
                    "review_group_id": "rg_missing",
                    "decision": "not_same",
                    "confidence": 0.9,
                    "rationale": "未知組",
                }
            ],
        }
        with self.assertRaises(PersistenceError):
            review_subjects.decision_entries_for_payload(batch_payload, status="resolved")
        # Duplicate candidate keys across the plan fail closed.
        dup = copy.deepcopy(initials)
        dup.append(copy.deepcopy(initials[0]))
        with self.assertRaises(PersistenceConflict):
            R.create_chapter_review_plan(
                job_id=job_id,
                revision_id=revision_id,
                assembled_bundle_sha256=sha256_json(bundle),
                base_catalog_sha256=sha256_json(catalog),
                initial_resolutions=dup,
                catalog=catalog,
                chapter_by_ref=chapters,
            )


class ChapterPublishTests(unittest.TestCase):
    def test_accepted_cross_chapter_same_merges_under_original_union(self) -> None:
        bundle, chapters = _chapter_bundle()
        initials = R.build_chapter_initial_resolutions(
            bundle=bundle,
            bundle_label="bund",
            chapter_by_ref=chapters,
            chapter_index_by_id=_chapter_index(),
            corpus={},
        )
        self.assertEqual(len(initials), 1)
        sha = R.initial_artifact_sha(initials[0])
        key = f"{sha}:ec_001"
        final = R.build_final_chapter_resolutions(
            initials,
            {
                key: {
                    "decision": "same_entity",
                    "confidence": 0.9,
                    "rationale": "兩章同名且第二共有表字證據",
                }
            },
        )
        self.assertEqual(final[0]["version"], "0.2")
        catalog, report = R.publish_with_decisions(
            bundles={"bund": bundle}, resolutions=final, existing_catalog=None
        )
        self.assertEqual(len(catalog["canonical_entities"]), 2)
        merged = [
            record
            for record in catalog["canonical_entities"]
            if len(record["representations"]) == 2
        ]
        self.assertEqual(len(merged), 1)
        self.assertEqual(
            merged[0]["representations"],
            [
                {"bundle": "bund", "ref": "ent_000001"},
                {"bundle": "bund", "ref": "ent_001001"},
            ],
        )
        self.assertEqual(report["decisions"]["entities"], {"same_entity": 1})

    def test_uncertain_without_evidence_stays_distinct(self) -> None:
        bundle, chapters = _chapter_bundle()
        initials = R.build_chapter_initial_resolutions(
            bundle=bundle,
            bundle_label="bund",
            chapter_by_ref=chapters,
            chapter_index_by_id=_chapter_index(),
            corpus={},
        )
        sha = R.initial_artifact_sha(initials[0])
        final = R.build_final_chapter_resolutions(
            initials,
            {
                f"{sha}:ec_001": {
                    "decision": "uncertain",
                    "confidence": 0.5,
                    "rationale": "同名無充分依據",
                }
            },
        )
        catalog, _ = R.publish_with_decisions(
            bundles={"bund": bundle}, resolutions=final, existing_catalog=None
        )
        self.assertEqual(len(catalog["canonical_entities"]), 3)

    def test_final_downgrade_to_01_is_refused(self) -> None:
        bundle, chapters = _chapter_bundle()
        initials = R.build_chapter_initial_resolutions(
            bundle=bundle,
            bundle_label="bund",
            chapter_by_ref=chapters,
            chapter_index_by_id=_chapter_index(),
            corpus={},
        )
        downgraded = copy.deepcopy(initials)
        downgraded[0]["version"] = "0.1"
        downgraded[0].pop("scope", None)
        sha = R.initial_artifact_sha(initials[0])
        with self.assertRaises(PersistenceError):
            R.build_final_chapter_resolutions(
                downgraded,
                {
                    f"{sha}:ec_001": {
                        "decision": "same_entity",
                        "confidence": 0.9,
                        "rationale": "降版探針",
                    }
                },
            )


class WithinBundleIndexOrderTests(unittest.TestCase):
    def _hash_chapters(self) -> tuple[dict, dict[str, str], dict[str, int]]:
        # Hash-like chapter ids whose string order disagrees with the
        # real chapter order: ch_zzz is chapter 0, ch_aaa is chapter 1.
        bundle = _bundle(
            "合裝本",
            [_entity("ent_b", "曹操"), _entity("ent_a", "曹操")],
            [],
        )
        chapters = {"ent_b": "ch_zzz", "ent_a": "ch_aaa"}
        index_by_id = {"ch_zzz": 0, "ch_aaa": 1}
        return bundle, chapters, index_by_id

    def test_left_follows_chapter_index_not_id_string_or_ref(self) -> None:
        import resolution_v0

        bundle, chapters, index_by_id = self._hash_chapters()
        candidates = resolution_v0.build_within_bundle_candidate_set(
            bundle, "bund", chapters, chapter_index_by_id=index_by_id
        )
        self.assertEqual(len(candidates["entity_candidates"]), 1)
        candidate = candidates["entity_candidates"][0]
        # Index 0 (ch_zzz/ent_b) is left even though 'ch_aaa' < 'ch_zzz'
        # and 'ent_a' < 'ent_b' as strings.
        self.assertEqual(candidate["left"], {"bundle": "bund", "ref": "ent_b"})
        self.assertEqual(candidate["right"], {"bundle": "bund", "ref": "ent_a"})

    def test_missing_chapter_index_fails_closed(self) -> None:
        import resolution_v0

        bundle, chapters, _ = self._hash_chapters()
        with self.assertRaises(resolution_v0.ResolutionV0Error):
            resolution_v0.build_within_bundle_candidate_set(
                bundle, "bund", chapters, chapter_index_by_id={"ch_zzz": 0}
            )

    def test_chapter_path_threads_the_index_map(self) -> None:
        bundle, chapters, index_by_id = self._hash_chapters()
        initials = R.build_chapter_initial_resolutions(
            bundle=bundle,
            bundle_label="bund",
            chapter_by_ref=chapters,
            chapter_index_by_id=index_by_id,
        )
        self.assertEqual(len(initials), 1)
        link = initials[0]["entity_links"][0]
        self.assertEqual(link["left"], {"bundle": "bund", "ref": "ent_b"})
        self.assertEqual(link["right"], {"bundle": "bund", "ref": "ent_a"})


class IllegalScopeCombinationTests(unittest.TestCase):
    def _within(self) -> dict:
        bundle, chapters = _chapter_bundle()
        initial = R.build_within_bundle_initial_resolution(
            bundle=bundle,
            bundle_label="bund",
            chapter_by_ref=chapters,
            chapter_index_by_id=_chapter_index(),
        )
        assert initial is not None
        return initial

    def test_missing_chapter_index_map_fails_closed(self) -> None:
        import resolution_v0

        bundle, chapters = _chapter_bundle()
        # Omitted map is a loud TypeError; an explicit None is a
        # PersistenceError: neither silently sorts by ref.
        with self.assertRaises(TypeError):
            R.build_within_bundle_initial_resolution(
                bundle=bundle, bundle_label="bund", chapter_by_ref=chapters
            )  # type: ignore[call-arg]
        with self.assertRaises(PersistenceError):
            R.build_within_bundle_initial_resolution(
                bundle=bundle,
                bundle_label="bund",
                chapter_by_ref=chapters,
                chapter_index_by_id=None,  # type: ignore[arg-type]
            )
        with self.assertRaises(TypeError):
            R.build_chapter_initial_resolutions(
                bundle=bundle, bundle_label="bund", chapter_by_ref=chapters
            )  # type: ignore[call-arg]
        with self.assertRaises(resolution_v0.ResolutionV0Error):
            resolution_v0.build_within_bundle_candidate_set(
                bundle, "bund", chapters, None  # type: ignore[arg-type]
            )

    def test_within_revision_with_two_bundles_is_rejected(self) -> None:
        import publication_v0

        initial = self._within()
        other = _bundle("他書", [_entity("ent_900", "曹操")], [])
        bundles = {"bund": _chapter_bundle()[0], "other": other}
        split = copy.deepcopy(initial)
        split["right_bundle"] = {
            "label": "other",
            "source_ref": "src_001",
            "source_title": "他書",
        }
        split["entity_links"][0]["right"] = {"bundle": "other", "ref": "ent_900"}
        with self.assertRaises(publication_v0.PublicationV0Error):
            publication_v0.publish_catalog(
                bundles, [split], existing_catalog=None
            )
        with self.assertRaises(PersistenceError):
            R.publish_with_decisions(
                bundles=bundles, resolutions=[split], existing_catalog=None
            )

    def test_scoped_01_is_rejected_by_publisher_and_store(self) -> None:
        import publication_v0
        import resolution_store

        initial = self._within()
        scoped_01 = copy.deepcopy(initial)
        scoped_01["version"] = "0.1"
        bundles = {"bund": _chapter_bundle()[0]}
        with self.assertRaises(publication_v0.PublicationV0Error):
            publication_v0.publish_catalog(
                bundles, [scoped_01], existing_catalog=None
            )
        with self.assertRaises(PersistenceError):
            resolution_store.validate_resolution_envelope(scoped_01)

    def test_same_bundle_01_is_rejected(self) -> None:
        import publication_v0

        bundles = {"bund": _chapter_bundle()[0]}
        legacy_same = {
            "schema": "chronicle.resolution-links",
            "version": "0.1",
            "left_bundle": {"label": "bund", "source_ref": "src_001", "source_title": "t"},
            "right_bundle": {"label": "bund", "source_ref": "src_001", "source_title": "t"},
            "entity_links": [],
            "event_links": [],
            "warnings": [],
        }
        with self.assertRaises(publication_v0.PublicationV0Error):
            publication_v0.publish_catalog(
                bundles, [legacy_same], existing_catalog=None
            )

    def test_cross_source_02_with_same_bundle_is_rejected(self) -> None:
        import publication_v0
        import resolution_store

        initial = self._within()
        cross_same = copy.deepcopy(initial)
        cross_same["scope"] = "cross_source"
        bundles = {"bund": _chapter_bundle()[0]}
        with self.assertRaises(publication_v0.PublicationV0Error):
            publication_v0.publish_catalog(
                bundles, [cross_same], existing_catalog=None
            )
        with self.assertRaises(PersistenceError):
            resolution_store.validate_resolution_envelope(cross_same)


if __name__ == "__main__":
    unittest.main()
