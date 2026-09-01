from __future__ import annotations

import unittest

from resolution_v0 import (
    ResolutionV0Error,
    apply_resolution_decisions,
    build_candidate_set,
    build_resolution_prompt,
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


def _event(ref: str, event_type: str, title: str, participant_ref: str, year: int) -> dict:
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
        "places": [],
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

    def test_event_blocking_uses_time_type_and_participant_overlap(self) -> None:
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

    def test_apply_decisions_preserves_candidate_refs(self) -> None:
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
