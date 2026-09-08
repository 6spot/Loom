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


if __name__ == "__main__":
    unittest.main()
