"""Unit contracts for Chronicle's strict model-output projection."""

from __future__ import annotations

import copy
import json
import sys
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

CANONICAL = HERE.parent / "ingestion" / "schemas" / "chronicle-v0.1.schema.json"


def sample_bundle() -> dict:
    return {
        "schema_version": "0.1",
        "source": {
            "temp_id": "src_001",
            "kind": "source",
            "source_type": "book",
            "title": "三国志·蜀书·先主传",
            "language": "zh-Hant",
            "extraction": {"method": "model"},
        },
        "entities": [
            {
                "temp_id": "ent_001",
                "kind": "entity",
                "type": "person",
                "canonical_name": "劉表",
                "aliases": [],
                "mentions": [{"text": "劉表"}],
                "resolution": {"status": "unresolved"},
                "extraction": {"method": "model"},
            }
        ],
        "events": [
            {
                "temp_id": "evt_001",
                "kind": "event",
                "type": "death",
                "title": "劉表卒",
                "time": None,
                "participants": [{"entity_ref": "ent_001", "role": "subject"}],
                "places": [],
                "extraction": {"method": "model"},
            }
        ],
        "claims": [
            {
                "temp_id": "clm_001",
                "kind": "claim",
                "subject": {"kind": "event_ref", "ref": "evt_001"},
                "predicate": "occurred",
                "object": None,
                "evidence": {
                    "text": "劉表卒",
                    "source_ref": "src_001",
                    "locator": {"section": "全文"},
                },
                "assessment": {"status": "unassessed"},
                "extraction": {"method": "model"},
            }
        ],
        "warnings": [],
    }


class ExtractionModelSchemaTests(unittest.TestCase):
    def test_projection_is_strict_and_named(self) -> None:
        fmt = S.extraction_text_format()
        self.assertEqual("json_schema", fmt["type"])
        self.assertEqual(S.FORMAT_NAME, fmt["name"])
        self.assertTrue(fmt["strict"])
        self.assertFalse(fmt["schema"]["additionalProperties"])

    def test_projection_sample_is_also_valid_canonical_bundle(self) -> None:
        bundle = sample_bundle()
        model_errors = list(Draft202012Validator(S.extraction_model_schema()).iter_errors(bundle))
        self.assertEqual([], model_errors)
        canonical = json.loads(CANONICAL.read_text(encoding="utf-8"))
        canonical_errors = list(Draft202012Validator(canonical).iter_errors(bundle))
        self.assertEqual([], canonical_errors)

    def test_projection_forbids_previous_live_drift_fields(self) -> None:
        schema = S.extraction_model_schema()
        source_props = schema["properties"]["source"]["properties"]
        locator_props = schema["properties"]["claims"]["items"]["properties"]["evidence"]["properties"]["locator"]["properties"]
        mention_props = schema["properties"]["entities"]["items"]["properties"]["mentions"]["items"]["properties"]
        self.assertNotIn("work", source_props)
        self.assertEqual({"section"}, set(locator_props))
        self.assertNotIn("contextual", mention_props)

    def test_r13_chunk_projection_keeps_resolution_unresolved(self) -> None:
        schema = S.extraction_model_schema()
        resolution_status = (
            schema["properties"]["entities"]["items"]["properties"]
            ["resolution"]["properties"]["status"]
        )
        self.assertEqual("unresolved", resolution_status["const"])
        self.assertNotIn("enum", resolution_status)

        for forbidden in ("ambiguous", "new", "resolved"):
            with self.subTest(status=forbidden):
                bundle = copy.deepcopy(sample_bundle())
                bundle["entities"][0]["resolution"]["status"] = forbidden
                model_errors = list(
                    Draft202012Validator(S.extraction_model_schema()).iter_errors(bundle)
                )
                self.assertTrue(model_errors)

        # The canonical schema remains broader on purpose: those statuses belong
        # to later resolution/canonical stages, not the chunk-extraction model.
        canonical = json.loads(CANONICAL.read_text(encoding="utf-8"))
        ambiguous = copy.deepcopy(sample_bundle())
        ambiguous["entities"][0]["resolution"]["status"] = "ambiguous"
        canonical_errors = list(Draft202012Validator(canonical).iter_errors(ambiguous))
        self.assertEqual([], canonical_errors)


# ---------------------------------------------------------------------------
# Chapter candidate projection (C2-R1-T06)
# ---------------------------------------------------------------------------

CHAPTER_TEXT = "建安十三年，曹操屯江陵。周瑜敗操於赤壁。"
CHAPTER_ID = "ch_" + "a1" * 12


def chapter_request() -> dict:
    import hashlib

    blocks = [
        {"block_id": "b_001", "kind": "body", "start": 0, "end": 12},
        {"block_id": "b_002", "kind": "body", "start": 12, "end": 20},
    ]
    text_hash = hashlib.sha256(CHAPTER_TEXT.encode("utf-8")).hexdigest()
    return {
        "chapter_id": CHAPTER_ID,
        "chapter_index": 0,
        "revision_id": "rev-t06-fixture-1",
        "source_sha256": text_hash,
        "normalized_sha256": text_hash,
        "normalized_text": CHAPTER_TEXT,
        "blocks": blocks,
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
        "schema_versions": {"candidate": "0.1", "bundle": "0.1"},
    }


def sample_chapter_candidate() -> dict:
    meta = {"method": "model", "job_id": None, "confidence": None}
    return {
        "schema": "chronicle.chapter-candidate",
        "version": "0.1",
        "chapter_id": CHAPTER_ID,
        "bundle": {
            "schema_version": "0.1",
            "source": {
                "temp_id": "src_001",
                "kind": "source",
                "source_type": "book",
                "title": "三國志·蜀書·先主傳",
                "language": "lzh",
                "extraction": dict(meta),
            },
            "entities": [
                {
                    "temp_id": "ent_001",
                    "kind": "entity",
                    "type": "person",
                    "canonical_name": "曹操",
                    "aliases": [],
                    "mentions": [{"text": "曹操", "contextual": False}],
                    "resolution": {"status": "unresolved"},
                    "extraction": dict(meta),
                },
                {
                    "temp_id": "ent_002",
                    "kind": "entity",
                    "type": "person",
                    "canonical_name": "周瑜",
                    "aliases": [],
                    "mentions": [{"text": "周瑜", "contextual": False}],
                    "resolution": {"status": "unresolved"},
                    "extraction": dict(meta),
                },
            ],
            "events": [
                {
                    "temp_id": "evt_001",
                    "kind": "event",
                    "type": "battle",
                    "title": "赤壁之戰",
                    "time": None,
                    "participants": [
                        {"entity_ref": "ent_001", "role": "commander"},
                        {"entity_ref": "ent_002", "role": "commander"},
                    ],
                    "places": [],
                    "extraction": dict(meta),
                }
            ],
            "claims": [
                {
                    "temp_id": "clm_001",
                    "kind": "claim",
                    "subject": {"kind": "entity", "ref": "ent_001"},
                    "predicate": "stationed_at",
                    "object": None,
                    "evidence": {
                        "text": "曹操屯江陵",
                        "source_ref": "src_001",
                        "locator": {"section": "b_001"},
                    },
                    "assessment": {"status": "unassessed"},
                    "extraction": dict(meta),
                }
            ],
            "warnings": [],
        },
        "translation": {
            "language": "zh-CN",
            "blocks": [
                {
                    "block_id": "t_001",
                    "text": "建安十三年曹操屯兵江陵。",
                    "source_block_ids": ["b_001"],
                    "entity_refs": [{"kind": "entity", "ref": "ent_001"}],
                    "event_refs": [],
                },
                {
                    "block_id": "t_002",
                    "text": "周瑜在赤壁擊敗曹操。",
                    "source_block_ids": ["b_002"],
                    "entity_refs": [
                        {"kind": "entity", "ref": "ent_001"},
                        {"kind": "entity", "ref": "ent_002"},
                    ],
                    "event_refs": [{"kind": "event", "ref": "evt_001"}],
                },
            ],
        },
        "mentions": [
            {
                "mention_id": "m_001",
                "surface": "曹操",
                "contextual": False,
                "status": "resolved",
                "target_ref": "ent_001",
                "candidate_refs": [],
                "selection": {
                    "first_block_id": "b_001",
                    "last_block_id": "b_001",
                    "quote": "曹操",
                    "occurrence": 1,
                },
            },
            {
                "mention_id": "m_002",
                "surface": "周瑜",
                "contextual": False,
                "status": "resolved",
                "target_ref": "ent_002",
                "candidate_refs": [],
                "selection": {
                    "first_block_id": "b_002",
                    "last_block_id": "b_002",
                    "quote": "周瑜",
                    "occurrence": 1,
                },
            },
        ],
        "record_sources": [
            {
                "record_ref": "ent_001",
                "record_kind": "entity",
                "selections": [
                    {
                        "first_block_id": "b_001",
                        "last_block_id": "b_001",
                        "quote": "曹操",
                        "occurrence": 1,
                    }
                ],
            },
            {
                "record_ref": "ent_002",
                "record_kind": "entity",
                "selections": [
                    {
                        "first_block_id": "b_002",
                        "last_block_id": "b_002",
                        "quote": "周瑜",
                        "occurrence": 1,
                    }
                ],
            },
            {
                "record_ref": "evt_001",
                "record_kind": "event",
                "selections": [
                    {
                        "first_block_id": "b_002",
                        "last_block_id": "b_002",
                        "quote": "敗操於赤壁",
                        "occurrence": 1,
                    }
                ],
            },
            {
                "record_ref": "clm_001",
                "record_kind": "claim",
                "selections": [
                    {
                        "first_block_id": "b_001",
                        "last_block_id": "b_001",
                        "quote": "曹操屯江陵",
                        "occurrence": 1,
                    }
                ],
            },
        ],
        "warnings": [],
    }


class ChapterCandidateProjectionTests(unittest.TestCase):
    def test_format_is_strict_and_named(self) -> None:
        fmt = S.chapter_candidate_text_format()
        self.assertEqual("json_schema", fmt["type"])
        self.assertEqual(S.CHAPTER_CANDIDATE_FORMAT_NAME, fmt["name"])
        self.assertTrue(fmt["strict"])
        Draft202012Validator.check_schema(fmt["schema"])

    def test_projection_avoids_composition_keywords(self) -> None:
        dumped = json.dumps(S.chapter_candidate_model_schema())
        for forbidden in ("allOf", "oneOf", "$ref", '"not"', "uniqueItems"):
            self.assertNotIn(forbidden, dumped)

    def test_projection_carries_no_program_generated_fields(self) -> None:
        schema = S.chapter_candidate_model_schema()

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
                for value in node.get("anyOf", []) if isinstance(node.get("anyOf"), list) else []:
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
            "request_fingerprint",
            "start",
            "end",
            "offset",
            "occurrence_count",
            "artifact",
            "provenance",
        ):
            self.assertNotIn(forbidden, names, f"program-bound field {forbidden!r} leaked")
        # The only model-legible identity slots are temp IDs and the request's
        # chapter echo; canonical_name is a model-extraction label, not a
        # canonical mapping.
        self.assertIn("temp_id", names)
        self.assertIn("chapter_id", names)

    def test_projection_sample_passes_t01_canonical_validator(self) -> None:
        import chapter_contract as C

        candidate = sample_chapter_candidate()
        projection_errors = list(
            Draft202012Validator(S.chapter_candidate_model_schema()).iter_errors(candidate)
        )
        self.assertEqual([], projection_errors)
        report = C.validate_chapter_candidate(chapter_request(), candidate)
        self.assertTrue(report["passed"], json.dumps(report["errors"], ensure_ascii=False))

    def test_projection_rejects_program_generated_drift(self) -> None:
        validator = Draft202012Validator(S.chapter_candidate_model_schema())
        candidate = sample_chapter_candidate()
        candidate["bundle"]["entities"][0]["resolution"] = {
            "status": "resolved",
            "canonical_id": "ent-canonical-1",
        }
        self.assertFalse(validator.is_valid(candidate))

        anchored = sample_chapter_candidate()
        anchored["mentions"][0]["selection"] = {
            "first_block_id": "b_001",
            "last_block_id": "b_001",
            "quote": "曹操",
            "occurrence": 1,
            "start": 6,
            "end": 8,
        }
        self.assertFalse(validator.is_valid(anchored))

    def test_projection_requires_chapter_binding_and_translation(self) -> None:
        validator = Draft202012Validator(S.chapter_candidate_model_schema())
        candidate = sample_chapter_candidate()
        candidate["chapter_id"] = "not-a-chapter-id"
        self.assertFalse(validator.is_valid(candidate))
        empty = sample_chapter_candidate()
        empty["translation"]["blocks"] = []
        self.assertFalse(validator.is_valid(empty))


if __name__ == "__main__":
    unittest.main()
