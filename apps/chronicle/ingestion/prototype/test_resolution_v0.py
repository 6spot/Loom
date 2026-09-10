from __future__ import annotations

import json
import unittest
from pathlib import Path

from chronicle_ingest import validate_bundle
from resolution_v0 import (
    ResolutionV0Error,
    apply_resolution_decisions,
    build_candidate_set,
    build_resolution_prompt,
    build_within_bundle_candidate_set,
)


def _entity(ref: str, entity_type: str, name: str) -> dict:
    return {
        "temp_id": ref,
        "kind": "entity",
        "type": entity_type,
        "canonical_name": name,
        "aliases": [],
        "mentions": [],
    }


def _event(
    ref: str,
    event_type: str,
    title: str,
    participant_ref: str,
    year: int,
    place_ref: str | None = None,
) -> dict:
    return {
        "temp_id": ref,
        "kind": "event",
        "type": event_type,
        "title": title,
        "time": {
            "original_text": "十三年",
            "source_calendar": {
                "system": "chinese_lunisolar_regnal",
                "era": "建安",
                "era_year": 13,
            },
            "normalized": {
                "calendar": "proleptic_gregorian",
                "year": year,
                "month": None,
                "day": None,
                "precision": "year",
                "conversion_status": "year_only",
            },
        },
        "participants": [{"entity_ref": participant_ref, "role": "subject"}],
        "places": [place_ref] if place_ref else [],
    }


def _bundle(title: str, entities: list[dict], events: list[dict]) -> dict:
    return {
        "schema_version": "0.1",
        "source": {"temp_id": "src_001", "kind": "source", "title": title},
        "entities": entities,
        "events": events,
        "claims": [],
        "warnings": [],
    }


def _event_multi(
    ref: str,
    event_type: str,
    title: str,
    participant_refs: list[str],
    year: int,
    place_refs: list[str] | None = None,
) -> dict:
    event = _event(ref, event_type, title, participant_refs[0], year)
    event["participants"] = [
        {"entity_ref": participant, "role": "subject"} for participant in participant_refs
    ]
    event["places"] = list(place_refs or [])
    return event


class ResolutionV0Tests(unittest.TestCase):
    def test_entity_blocking_requires_same_type_and_stable_surface(self) -> None:
        left = _bundle("left", [_entity("ent_001", "person", "刘表")], [])
        right = _bundle(
            "right",
            [
                _entity("ent_010", "person", "刘表"),
                _entity("ent_011", "place", "刘表"),
                _entity("ent_012", "person", "刘琮"),
            ],
            [],
        )
        candidates = build_candidate_set(left, "left", right, "right")
        self.assertEqual(1, len(candidates["entity_candidates"]))
        candidate = candidates["entity_candidates"][0]
        self.assertEqual("ent_001", candidate["left"]["ref"])
        self.assertEqual("ent_010", candidate["right"]["ref"])

    def test_event_blocking_allows_low_ambiguity_same_type_and_participant(self) -> None:
        left = _bundle(
            "left",
            [_entity("ent_001", "person", "刘表")],
            [_event("evt_001", "death", "刘表死", "ent_001", 208)],
        )
        right = _bundle(
            "right",
            [_entity("ent_010", "person", "刘表")],
            [
                _event("evt_010", "death", "荆州牧刘表死", "ent_010", 208),
                _event("evt_011", "death", "另一年刘表死", "ent_010", 209),
            ],
        )
        candidates = build_candidate_set(left, "left", right, "right")
        self.assertEqual(1, len(candidates["event_candidates"]))
        self.assertEqual("evt_010", candidates["event_candidates"][0]["right"]["ref"])

    def test_broad_event_does_not_block_on_one_shared_participant_alone(self) -> None:
        left = _bundle(
            "left",
            [_entity("ent_001", "person", "曹操")],
            [_event("evt_001", "military", "曹操南征", "ent_001", 208)],
        )
        right = _bundle(
            "right",
            [_entity("ent_010", "person", "曹操")],
            [_event("evt_010", "battle", "赤壁之战", "ent_010", 208)],
        )
        candidates = build_candidate_set(left, "left", right, "right")
        self.assertEqual([], candidates["event_candidates"])

    def test_broad_event_requires_shared_participant_and_place_anchor(self) -> None:
        left = _bundle(
            "left",
            [
                _entity("ent_001", "person", "孙权"),
                _entity("ent_002", "place", "合肥"),
            ],
            [_event("evt_001", "battle", "孙权攻合肥", "ent_001", 208, "ent_002")],
        )
        right = _bundle(
            "right",
            [
                _entity("ent_010", "person", "孙权"),
                _entity("ent_011", "place", "合肥"),
            ],
            [_event("evt_010", "military", "孙权围合肥", "ent_010", 208, "ent_011")],
        )
        candidates = build_candidate_set(left, "left", right, "right")
        self.assertEqual(1, len(candidates["event_candidates"]))
        self.assertIn("shared places: 合肥", candidates["event_candidates"][0]["signals"])

    def test_broad_event_title_place_anchor_when_one_side_omits_place(self) -> None:
        # Live regression (C2-R1-T19 C04): 先主傳 赤壁之戰 records no place ref
        # but names the battle site in the title; 周瑜傳 赤壁之戰火攻曹軍 carries
        # the 赤壁 place. The title place is the shared anchor, not the
        # participant count.
        left = _bundle(
            "left",
            [
                _entity("ent_001", "person", "劉備"),
                _entity("ent_002", "person", "曹操"),
                _entity("ent_003", "person", "孫權"),
                _entity("ent_004", "place", "赤壁"),
            ],
            [
                _event_multi(
                    "evt_001", "battle", "赤壁之戰",
                    ["ent_001", "ent_002", "ent_003"], 208,
                )
            ],
        )
        right = _bundle(
            "right",
            [
                _entity("ent_010", "person", "劉備"),
                _entity("ent_011", "person", "曹操"),
                _entity("ent_012", "person", "孫權"),
                _entity("ent_013", "person", "周瑜"),
                _entity("ent_014", "place", "赤壁"),
            ],
            [
                _event_multi(
                    "evt_010", "battle", "赤壁火攻",
                    ["ent_013", "ent_012", "ent_011", "ent_010"], 208,
                    ["ent_014"],
                )
            ],
        )
        candidates = build_candidate_set(left, "left", right, "right")
        self.assertEqual(1, len(candidates["event_candidates"]))
        self.assertIn(
            "shared places: 赤壁",
            candidates["event_candidates"][0]["signals"],
        )

    def test_broad_event_participants_alone_do_not_block(self) -> None:
        # Live counterexample (C2-R1-T19): 劉備取得益州 and 劉備割湘水為界並罷軍
        # share 劉備/孫權 and no shared-place anchor, so they must not block.
        left = _bundle(
            "left",
            [
                _entity("ent_001", "person", "劉備"),
                _entity("ent_002", "person", "孫權"),
            ],
            [
                _event_multi(
                    "evt_001", "territorial_change", "劉備取得益州",
                    ["ent_001", "ent_002"], 214,
                )
            ],
        )
        right = _bundle(
            "right",
            [
                _entity("ent_010", "person", "劉備"),
                _entity("ent_011", "person", "孫權"),
            ],
            [
                _event_multi(
                    "evt_010", "territorial_change", "劉備割湘水為界並罷軍",
                    ["ent_010", "ent_011"], 214,
                )
            ],
        )
        candidates = build_candidate_set(left, "left", right, "right")
        self.assertEqual([], candidates["event_candidates"])

    def test_broad_event_related_title_without_shared_place_do_not_block(self) -> None:
        # Live counterexample (C2-R1-T19): 赤壁之戰 vs 曹操敗退 share
        # participants but the titles name different (or no) places.
        left = _bundle(
            "left",
            [
                _entity("ent_001", "person", "曹操"),
                _entity("ent_002", "person", "劉備"),
                _entity("ent_003", "place", "赤壁"),
            ],
            [
                _event_multi(
                    "evt_001", "battle", "赤壁之戰",
                    ["ent_001", "ent_002"], 208,
                )
            ],
        )
        right = _bundle(
            "right",
            [
                _entity("ent_010", "person", "曹操"),
                _entity("ent_011", "person", "劉備"),
                _entity("ent_012", "place", "江東"),
            ],
            [
                _event_multi(
                    "evt_010", "military", "曹操敗退",
                    ["ent_010", "ent_011"], 208, ["ent_012"],
                )
            ],
        )
        candidates = build_candidate_set(left, "left", right, "right")
        self.assertEqual([], candidates["event_candidates"])

    def test_broad_event_conflicting_places_do_not_block(self) -> None:
        # Two shared participants are not enough when both chapters name
        # different places: that is a different occurrence, not a candidate.
        left = _bundle(
            "left",
            [
                _entity("ent_001", "person", "曹操"),
                _entity("ent_002", "person", "劉備"),
                _entity("ent_003", "place", "徐州"),
            ],
            [
                _event_multi(
                    "evt_001", "battle", "曹操征徐州",
                    ["ent_001", "ent_002"], 208, ["ent_003"],
                )
            ],
        )
        right = _bundle(
            "right",
            [
                _entity("ent_010", "person", "曹操"),
                _entity("ent_011", "person", "劉備"),
                _entity("ent_012", "place", "赤壁"),
            ],
            [
                _event_multi(
                    "evt_010", "battle", "赤壁之戰",
                    ["ent_010", "ent_011"], 208, ["ent_012"],
                )
            ],
        )
        candidates = build_candidate_set(left, "left", right, "right")
        self.assertEqual([], candidates["event_candidates"])

    def test_within_bundle_event_candidate_when_one_side_omits_place(self) -> None:
        # Same rule on the within-revision (cross-chapter) path that C04 uses.
        bundle = _bundle(
            "book",
            [
                _entity("ent_001", "person", "劉備"),
                _entity("ent_002", "person", "曹操"),
                _entity("ent_003", "person", "孫權"),
                _entity("ent_004", "person", "周瑜"),
                _entity("ent_005", "place", "赤壁"),
            ],
            [
                _event_multi(
                    "evt_001", "battle", "赤壁之戰",
                    ["ent_001", "ent_002", "ent_003"], 208,
                ),
                _event_multi(
                    "evt_002", "battle", "赤壁火攻",
                    ["ent_004", "ent_003", "ent_002", "ent_001"], 208,
                    ["ent_005"],
                ),
            ],
        )
        chapter_by_ref = {
            "evt_001": "ch_a",
            "evt_002": "ch_b",
        }
        out = build_within_bundle_candidate_set(
            bundle, "book", chapter_by_ref, {"ch_a": 0, "ch_b": 1}
        )
        self.assertEqual(1, len(out["event_candidates"]))
        candidate = out["event_candidates"][0]
        self.assertEqual("evt_001", candidate["left"]["ref"])
        self.assertEqual("evt_002", candidate["right"]["ref"])

    def test_within_bundle_participants_alone_do_not_block(self) -> None:
        # Same guard on the within-revision path: cross-chapter broad events
        # that share only participants must not become candidates.
        bundle = _bundle(
            "book",
            [
                _entity("ent_001", "person", "劉備"),
                _entity("ent_002", "person", "孫權"),
            ],
            [
                _event_multi(
                    "evt_001", "territorial_change", "劉備取得益州",
                    ["ent_001", "ent_002"], 214,
                ),
                _event_multi(
                    "evt_002", "territorial_change", "劉備割湘水為界並罷軍",
                    ["ent_001", "ent_002"], 214,
                ),
            ],
        )
        out = build_within_bundle_candidate_set(
            bundle, "book", {"evt_001": "ch_a", "evt_002": "ch_b"}, {"ch_a": 0, "ch_b": 1}
        )
        self.assertEqual([], out["event_candidates"])

    def test_prompt_is_closed_world_and_non_destructive(self) -> None:
        candidates = {
            "schema": "chronicle.resolution-candidates",
            "version": "0.1",
            "left_bundle": {"label": "a", "source_ref": "src_001", "source_title": "A"},
            "right_bundle": {"label": "b", "source_ref": "src_001", "source_title": "B"},
            "entity_candidates": [],
            "event_candidates": [],
        }
        prompt = build_resolution_prompt(candidates)
        self.assertIn("Use only the supplied candidate records and signals", prompt)
        self.assertIn("must remain immutable", prompt)
        self.assertIn("Do not invent canonical UUIDs", prompt)
        self.assertNotIn("expected.yaml", prompt)
        self.assertNotIn("human gold", prompt.lower())

    def test_apply_decisions_preserves_candidate_refs_and_schema(self) -> None:
        left = _bundle("left", [_entity("ent_001", "person", "刘表")], [])
        right = _bundle("right", [_entity("ent_010", "person", "刘表")], [])
        candidates = build_candidate_set(left, "left", right, "right")
        output = apply_resolution_decisions(
            candidates,
            {
                "entity_decisions": [
                    {
                        "candidate_id": "ec_001",
                        "decision": "same_entity",
                        "confidence": 0.99,
                        "rationale": "same type and same stable source surface",
                    }
                ],
                "event_decisions": [],
            },
        )
        link = output["entity_links"][0]
        self.assertEqual({"bundle": "left", "ref": "ent_001"}, link["left"])
        self.assertEqual({"bundle": "right", "ref": "ent_010"}, link["right"])
        self.assertEqual("same_entity", link["decision"])

        schema_path = Path(__file__).parent.parent / "schemas" / "chronicle-resolution-v0.1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual([], validate_bundle(output, schema))

    def test_missing_candidate_decision_is_rejected(self) -> None:
        left = _bundle("left", [_entity("ent_001", "person", "刘表")], [])
        right = _bundle("right", [_entity("ent_010", "person", "刘表")], [])
        candidates = build_candidate_set(left, "left", right, "right")
        with self.assertRaises(ResolutionV0Error):
            apply_resolution_decisions(
                candidates,
                {"entity_decisions": [], "event_decisions": []},
            )


if __name__ == "__main__":
    unittest.main()
