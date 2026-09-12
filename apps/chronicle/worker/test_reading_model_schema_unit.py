"""Unit contracts for the C2-R2-T03 reading structured-output projection.

The strict Responses projection must add the reading block on top of the
frozen 0.1 joint shape, expose version 0.2, and still carry no program-bound
values (coordinates, hashes, canonical/unit/stream IDs). The fixture reading
provider is checked against the same projection so live and development
outputs share one shape, and the T01 ``reading_contract`` remains the
acceptance authority.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
PERSISTENCE = HERE.parent / "persistence"
if str(PERSISTENCE) not in sys.path:
    sys.path.insert(0, str(PERSISTENCE))

import extraction_model_schema as S  # noqa: E402

CHAPTER_TEXT = "建安十三年，曹操屯江陵。周瑜敗操於赤壁。"
CHAPTER_ID = "ch_" + "d4" * 12


def chapter_request() -> dict:
    text_hash = hashlib.sha256(CHAPTER_TEXT.encode("utf-8")).hexdigest()
    return {
        "chapter_id": CHAPTER_ID,
        "chapter_index": 0,
        "revision_id": "rev-c2r2-schema-fixture",
        "source_sha256": text_hash,
        "normalized_sha256": text_hash,
        "normalized_text": CHAPTER_TEXT,
        "blocks": [
            {"block_id": "b_001", "kind": "body", "start": 0, "end": 12},
            {"block_id": "b_002", "kind": "body", "start": 12, "end": 20},
        ],
        "required_block_ids": ["b_001", "b_002"],
        "plan_version": "c2r1-chapters-v1",
        "limits": {
            "max_source_chars": 32768,
            "max_prompt_chars": 262144,
            "max_response_chars": 524288,
            "max_response_bytes": 4194304,
            "max_output_tokens": 65536,
            "max_correction_rounds": 1,
        },
        "schema_versions": {"candidate": "0.2", "bundle": "0.1"},
    }


def chapter_pack_payload() -> dict:
    return {
        "schema": "chronicle.chapter-fixture-pack",
        "version": "0.1",
        "model_version": "chronicle-c2r2-schema-fixture-v1",
        "chapters": [
            {
                "chapter_id": CHAPTER_ID,
                "revision_id": "rev-c2r2-schema-fixture",
                "source_title": "三國志·蜀書·先主傳",
                "translation_text": "建安十三年曹操屯兵江陵，周瑜於赤壁破操。",
                "entities": [
                    {"name": "曹操", "type": "person", "mention": "曹操"},
                    {"name": "周瑜", "type": "person", "mention": "周瑜"},
                ],
                "event": {"type": "battle", "title": "赤壁之戰"},
                "predicate": "stationed_at",
            }
        ],
    }


def fixture_reading_candidate() -> tuple[dict, dict]:
    import fixture_model

    tmp = Path(tempfile.mkdtemp())
    path = tmp / "chapter-pack.json"
    path.write_text(json.dumps(chapter_pack_payload(), ensure_ascii=False), encoding="utf-8")
    model = fixture_model.models_from_reading_chapter_fixture_pack(path)
    request = chapter_request()
    return request, model.build_for_request(request)


class ReadingProjectionTests(unittest.TestCase):
    def test_format_is_strict_named_and_schema_valid(self) -> None:
        fmt = S.chapter_candidate_text_format()
        self.assertEqual("json_schema", fmt["type"])
        self.assertEqual(S.CHAPTER_CANDIDATE_FORMAT_NAME, fmt["name"])
        self.assertTrue(fmt["strict"])
        Draft202012Validator.check_schema(fmt["schema"])

    def test_projection_requires_reading_and_version_0_2(self) -> None:
        schema = S.reading_chapter_candidate_model_schema()
        self.assertIn("reading", schema["required"])
        self.assertEqual("0.2", schema["properties"]["version"]["const"])
        reading = schema["properties"]["reading"]
        self.assertEqual(["units", "warnings"], reading["required"])
        self.assertNotIn("$ref", json.dumps(reading))

    def test_version_dispatch_keeps_0_1_0_2_0_3_apart(self) -> None:
        legacy = S.chapter_candidate_text_format_for("0.1")
        reading = S.chapter_candidate_text_format_for("0.2")
        person_state = S.chapter_candidate_text_format_for("0.3")
        self.assertNotIn("reading", legacy["schema"]["properties"])
        self.assertEqual("0.1", legacy["schema"]["properties"]["version"]["const"])
        self.assertIn("reading", reading["schema"]["properties"])
        self.assertNotIn("person_states", reading["schema"]["properties"])
        self.assertEqual("0.2", reading["schema"]["properties"]["version"]["const"])
        self.assertIn("reading", person_state["schema"]["properties"])
        self.assertIn("person_states", person_state["schema"]["properties"])
        self.assertEqual("0.3", person_state["schema"]["properties"]["version"]["const"])
        # The production format is now the 0.3 person-state projection.
        self.assertEqual(person_state, S.chapter_candidate_text_format())

    def test_projection_carries_no_program_generated_fields(self) -> None:
        schema = S.reading_chapter_candidate_model_schema()

        names: set[str] = set()

        def collect(node: object) -> None:
            if isinstance(node, dict):
                properties = node.get("properties")
                if isinstance(properties, dict):
                    for key, value in properties.items():
                        names.add(key)
                        collect(value)
                items = node.get("items")
                if isinstance(items, dict):
                    collect(items)
                anyof = node.get("anyOf")
                if isinstance(anyof, list):
                    for value in anyof:
                        collect(value)
            elif isinstance(node, list):
                for entry in node:
                    collect(entry)

        collect(schema)
        for forbidden in (
            "anchor_id",
            "quote_sha256",
            "canonical_id",
            "candidate_ids",
            "stream_id",
            "unit_id",
            "publication_id",
            "request_fingerprint",
            "start",
            "end",
            "artifact",
            "provenance",
        ):
            self.assertNotIn(forbidden, names, f"program-bound field {forbidden!r} leaked")
        self.assertIn("block_id", names)
        self.assertIn("narrative_time", names)
        self.assertIn("event_spans", names)
        self.assertIn("context_entities", names)

    def test_fixture_reading_candidate_matches_projection_and_validator(self) -> None:
        import reading_contract as R

        request, candidate = fixture_reading_candidate()
        projection = Draft202012Validator(S.reading_chapter_candidate_model_schema())
        projection_errors = sorted(
            error.message for error in projection.iter_errors(candidate)
        )
        self.assertEqual([], projection_errors)
        report = R.validate_reading_annotations(request, candidate)
        self.assertTrue(report["passed"], json.dumps(report["errors"], ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
