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

HERE = Path(__file__).resolve().parent
for path in (str(HERE),):
    if path not in sys.path:
        sys.path.insert(0, path)

import resolve_publish as R  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
