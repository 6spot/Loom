from __future__ import annotations

import copy
import json
import unittest
import uuid
from pathlib import Path

from chronicle_ingest import validate_bundle
from publication_v0 import (
    PublicationConflict,
    PublicationV0Error,
    new_uuid7,
    publish_catalog,
)


def _u(index: int) -> str:
    return f"00000000-0000-7000-8000-{index:012x}"


class _Ids:
    def __init__(self, start: int = 1) -> None:
        self.next = start

    def __call__(self) -> str:
        value = _u(self.next)
        self.next += 1
        return value


def _entity(ref: str) -> dict:
    return {"temp_id": ref, "kind": "entity"}


def _event(ref: str) -> dict:
    return {"temp_id": ref, "kind": "event"}


def _bundle(title: str, entities: list[str], events: list[str]) -> dict:
    return {
        "schema_version": "0.1",
        "source": {"temp_id": "src_001", "kind": "source", "title": title},
        "entities": [_entity(ref) for ref in entities],
        "events": [_event(ref) for ref in events],
        "claims": [],
        "warnings": [],
    }


def _resolution(
    left_label: str,
    left_title: str,
    right_label: str,
    right_title: str,
    entity_links: list[dict] | None = None,
    event_links: list[dict] | None = None,
) -> dict:
    return {
        "schema": "chronicle.resolution-links",
        "version": "0.1",
        "left_bundle": {
            "label": left_label,
            "source_ref": "src_001",
            "source_title": left_title,
        },
        "right_bundle": {
            "label": right_label,
            "source_ref": "src_001",
            "source_title": right_title,
        },
        "entity_links": entity_links or [],
        "event_links": event_links or [],
        "warnings": [],
    }


def _link(
    candidate_id: str,
    left_bundle: str,
    left_ref: str,
    right_bundle: str,
    right_ref: str,
    decision: str,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "left": {"bundle": left_bundle, "ref": left_ref},
        "right": {"bundle": right_bundle, "ref": right_ref},
        "decision": decision,
        "confidence": 1.0,
        "rationale": "test",
        "signals": [],
    }


class PublicationV0Tests(unittest.TestCase):
    def test_uuid7_generator_uses_version_7_and_rfc_variant(self) -> None:
        value = uuid.UUID(new_uuid7())
        self.assertEqual(7, value.version)
        self.assertEqual(uuid.RFC_4122, value.variant)

    def test_same_links_merge_and_other_records_remain_singletons(self) -> None:
        bundles = {
            "a": _bundle("A", ["ent_001", "ent_002"], ["evt_001", "evt_002"]),
            "b": _bundle("B", ["ent_010", "ent_011"], ["evt_010", "evt_011"]),
        }
        resolution = _resolution(
            "a",
            "A",
            "b",
            "B",
            entity_links=[
                _link("ec_001", "a", "ent_001", "b", "ent_010", "same_entity"),
                _link("ec_002", "a", "ent_002", "b", "ent_011", "uncertain"),
            ],
            event_links=[
                _link("vc_001", "a", "evt_001", "b", "evt_010", "same_occurrence"),
                _link("vc_002", "a", "evt_002", "b", "evt_011", "related_occurrence"),
            ],
        )
        catalog = publish_catalog(bundles, [resolution], id_factory=_Ids())

        self.assertEqual(3, len(catalog["canonical_entities"]))
        self.assertEqual(3, len(catalog["canonical_events"]))
        merged_entities = [
            record
            for record in catalog["canonical_entities"]
            if len(record["representations"]) == 2
        ]
        merged_events = [
            record
            for record in catalog["canonical_events"]
            if len(record["representations"]) == 2
        ]
        self.assertEqual(1, len(merged_entities))
        self.assertEqual(1, len(merged_events))
        self.assertEqual(1, len(catalog["event_relations"]))
        relation = catalog["event_relations"][0]
        self.assertNotEqual(
            relation["left_canonical_event_id"], relation["right_canonical_event_id"]
        )
        self.assertEqual("vc_002", relation["resolution_links"][0]["candidate_id"])

    def test_same_links_are_transitive_across_multiple_sources(self) -> None:
        bundles = {
            "a": _bundle("A", ["ent_001"], []),
            "b": _bundle("B", ["ent_010"], []),
            "c": _bundle("C", ["ent_020"], []),
        }
        ab = _resolution(
            "a",
            "A",
            "b",
            "B",
            entity_links=[
                _link("ec_001", "a", "ent_001", "b", "ent_010", "same_entity")
            ],
        )
        bc = _resolution(
            "b",
            "B",
            "c",
            "C",
            entity_links=[
                _link("ec_001", "b", "ent_010", "c", "ent_020", "same_entity")
            ],
        )
        catalog = publish_catalog(bundles, [ab, bc], id_factory=_Ids())
        self.assertEqual(1, len(catalog["canonical_entities"]))
        self.assertEqual(3, len(catalog["canonical_entities"][0]["representations"]))

    def test_existing_identity_is_reused_and_new_representation_attaches(self) -> None:
        existing = {
            "schema": "chronicle.canonical-catalog",
            "version": "0.1",
            "canonical_entities": [
                {
                    "canonical_id": _u(100),
                    "representations": [{"bundle": "a", "ref": "ent_001"}],
                },
                {
                    "canonical_id": _u(101),
                    "representations": [{"bundle": "legacy", "ref": "ent_900"}],
                },
            ],
            "canonical_events": [],
            "event_relations": [],
            "warnings": [],
        }
        bundles = {
            "a": _bundle("A", ["ent_001"], []),
            "b": _bundle("B", ["ent_010"], []),
        }
        resolution = _resolution(
            "a",
            "A",
            "b",
            "B",
            entity_links=[
                _link("ec_001", "a", "ent_001", "b", "ent_010", "same_entity")
            ],
        )
        catalog = publish_catalog(
            bundles, [resolution], existing_catalog=existing, id_factory=_Ids()
        )
        by_id = {
            record["canonical_id"]: record for record in catalog["canonical_entities"]
        }
        self.assertEqual(
            [
                {"bundle": "a", "ref": "ent_001"},
                {"bundle": "b", "ref": "ent_010"},
            ],
            by_id[_u(100)]["representations"],
        )
        self.assertIn(_u(101), by_id)
        self.assertEqual(
            [{"bundle": "legacy", "ref": "ent_900"}],
            by_id[_u(101)]["representations"],
        )

    def test_rerun_with_existing_catalog_is_identity_stable(self) -> None:
        bundles = {"a": _bundle("A", ["ent_001", "ent_002"], ["evt_001"])}
        first = publish_catalog(bundles, [], id_factory=_Ids())
        second = publish_catalog(
            bundles, [], existing_catalog=first, id_factory=_Ids(900)
        )
        self.assertEqual(first, second)

    def test_conflicting_existing_ids_fail_instead_of_collapsing(self) -> None:
        existing = {
            "schema": "chronicle.canonical-catalog",
            "version": "0.1",
            "canonical_entities": [
                {
                    "canonical_id": _u(100),
                    "representations": [{"bundle": "a", "ref": "ent_001"}],
                },
                {
                    "canonical_id": _u(101),
                    "representations": [{"bundle": "b", "ref": "ent_010"}],
                },
            ],
            "canonical_events": [],
            "event_relations": [],
            "warnings": [],
        }
        bundles = {
            "a": _bundle("A", ["ent_001"], []),
            "b": _bundle("B", ["ent_010"], []),
        }
        resolution = _resolution(
            "a",
            "A",
            "b",
            "B",
            entity_links=[
                _link("ec_001", "a", "ent_001", "b", "ent_010", "same_entity")
            ],
        )
        with self.assertRaises(PublicationConflict):
            publish_catalog(
                bundles, [resolution], existing_catalog=existing, id_factory=_Ids()
            )

    def test_not_same_conflict_is_detected_after_transitive_merge(self) -> None:
        bundles = {
            "a": _bundle("A", ["ent_001"], []),
            "b": _bundle("B", ["ent_010"], []),
            "c": _bundle("C", ["ent_020"], []),
        }
        ab = _resolution(
            "a",
            "A",
            "b",
            "B",
            entity_links=[
                _link("ec_001", "a", "ent_001", "b", "ent_010", "same_entity")
            ],
        )
        bc = _resolution(
            "b",
            "B",
            "c",
            "C",
            entity_links=[
                _link("ec_001", "b", "ent_010", "c", "ent_020", "same_entity")
            ],
        )
        ac = _resolution(
            "a",
            "A",
            "c",
            "C",
            entity_links=[
                _link("ec_001", "a", "ent_001", "c", "ent_020", "not_same")
            ],
        )
        with self.assertRaises(PublicationConflict):
            publish_catalog(bundles, [ab, bc, ac], id_factory=_Ids())

    def test_related_occurrence_cannot_end_up_in_same_canonical_event(self) -> None:
        bundles = {
            "a": _bundle("A", [], ["evt_001"]),
            "b": _bundle("B", [], ["evt_010"]),
            "c": _bundle("C", [], ["evt_020"]),
        }
        ab = _resolution(
            "a",
            "A",
            "b",
            "B",
            event_links=[
                _link(
                    "vc_001", "a", "evt_001", "b", "evt_010", "same_occurrence"
                )
            ],
        )
        bc = _resolution(
            "b",
            "B",
            "c",
            "C",
            event_links=[
                _link(
                    "vc_001", "b", "evt_010", "c", "evt_020", "same_occurrence"
                )
            ],
        )
        ac = _resolution(
            "a",
            "A",
            "c",
            "C",
            event_links=[
                _link(
                    "vc_001",
                    "a",
                    "evt_001",
                    "c",
                    "evt_020",
                    "related_occurrence",
                )
            ],
        )
        with self.assertRaises(PublicationConflict):
            publish_catalog(bundles, [ab, bc, ac], id_factory=_Ids())

    def test_inputs_are_not_modified_and_output_matches_schema(self) -> None:
        bundles = {
            "a": _bundle("A", ["ent_001"], ["evt_001"]),
            "b": _bundle("B", ["ent_010"], ["evt_010"]),
        }
        resolution = _resolution(
            "a",
            "A",
            "b",
            "B",
            entity_links=[
                _link("ec_001", "a", "ent_001", "b", "ent_010", "same_entity")
            ],
            event_links=[
                _link(
                    "vc_001", "a", "evt_001", "b", "evt_010", "same_occurrence"
                )
            ],
        )
        bundles_before = copy.deepcopy(bundles)
        resolution_before = copy.deepcopy(resolution)
        catalog = publish_catalog(bundles, [resolution], id_factory=_Ids())
        self.assertEqual(bundles_before, bundles)
        self.assertEqual(resolution_before, resolution)

        schema_path = (
            Path(__file__).parent.parent
            / "schemas"
            / "chronicle-canonical-v0.1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual([], validate_bundle(catalog, schema))

    def test_existing_related_occurrence_relation_is_preserved(self) -> None:
        existing = {
            "schema": "chronicle.canonical-catalog",
            "version": "0.1",
            "canonical_entities": [],
            "canonical_events": [
                {
                    "canonical_id": _u(200),
                    "representations": [{"bundle": "legacy", "ref": "evt_900"}],
                },
                {
                    "canonical_id": _u(201),
                    "representations": [{"bundle": "legacy", "ref": "evt_901"}],
                },
            ],
            "event_relations": [
                {
                    "type": "related_occurrence",
                    "left_canonical_event_id": _u(200),
                    "right_canonical_event_id": _u(201),
                    "resolution_links": [
                        {
                            "candidate_id": "vc_900",
                            "left": {"bundle": "legacy_a", "ref": "evt_900"},
                            "right": {"bundle": "legacy_b", "ref": "evt_901"},
                        }
                    ],
                }
            ],
            "warnings": [],
        }
        catalog = publish_catalog(
            {"a": _bundle("A", [], [])},
            [],
            existing_catalog=existing,
            id_factory=_Ids(),
        )
        self.assertEqual(existing["event_relations"], catalog["event_relations"])

    def test_resolution_bundle_metadata_must_match_staged_bundle(self) -> None:
        bundles = {
            "a": _bundle("A", ["ent_001"], []),
            "b": _bundle("B", ["ent_010"], []),
        }
        resolution = _resolution("a", "WRONG", "b", "B")
        with self.assertRaises(PublicationV0Error):
            publish_catalog(bundles, [resolution], id_factory=_Ids())


if __name__ == "__main__":
    unittest.main()
