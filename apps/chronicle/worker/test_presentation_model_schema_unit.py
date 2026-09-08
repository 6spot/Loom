"""Reader structured output must preserve the canonical candidate shape."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

HERE = Path(__file__).resolve().parent
for path in (HERE, HERE.parent / "persistence"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import presentation_model_schema as S  # noqa: E402
from test_presentation_r20_contract_unit import candidate  # noqa: E402


class PresentationModelSchemaTests(unittest.TestCase):
    def test_both_targets_satisfy_model_and_canonical_schemas(self) -> None:
        fmt = S.presentation_text_format()
        self.assertEqual("json_schema", fmt["type"])
        self.assertEqual(S.FORMAT_NAME, fmt["name"])
        self.assertTrue(fmt["strict"])
        canonical = json.loads(S.CANONICAL_SCHEMA.read_text(encoding="utf-8"))
        for target in ("entity", "event"):
            for schema in (fmt["schema"], canonical):
                with self.subTest(target=target, schema=schema.get("title")):
                    Draft202012Validator.check_schema(schema)
                    Draft202012Validator(schema, format_checker=FormatChecker()).validate(candidate(target))

    def test_strict_schema_rejects_r20_header_and_block_drift(self) -> None:
        validator = Draft202012Validator(S.presentation_model_schema(), format_checker=FormatChecker())
        for field in candidate():
            for value in ("missing", None):
                with self.subTest(field=field, value=value):
                    output = candidate()
                    if value == "missing":
                        del output[field]
                    else:
                        output[field] = value
                    self.assertFalse(validator.is_valid(output))
        for field, value in (("target_kind", "person"), ("canonical_id", "ent_001"), ("language", "en")):
            output = candidate()
            output[field] = value
            self.assertFalse(validator.is_valid(output))
        output = candidate()
        output["blocks"][0]["claim_refs"] = ["wudi:clm_008"]
        self.assertFalse(validator.is_valid(output))
        output = candidate()
        output["blocks"][0]["claim_refs"] *= 17
        self.assertFalse(validator.is_valid(output))

    def test_provider_adaptation_only_removes_annotations_and_unique_items(self) -> None:
        canonical = json.loads(S.CANONICAL_SCHEMA.read_text(encoding="utf-8"))
        original = copy.deepcopy(canonical)
        adapted = S.presentation_model_schema()

        def compare(source: dict, model: dict) -> None:
            expected = {k: v for k, v in source.items() if k not in {"$schema", "$id", "title", "uniqueItems", "properties", "items"}}
            if "const" in source or "enum" in source:
                expected.setdefault("type", "string")
            self.assertEqual(expected, {k: v for k, v in model.items() if k not in {"properties", "items"}})
            if source.get("type") == "object":
                self.assertFalse(model["additionalProperties"])
                self.assertEqual(set(model["properties"]), set(model["required"]))
                for key, prop in source["properties"].items():
                    compare(prop, model["properties"][key])
            if "items" in source:
                compare(source["items"], model["items"])

        compare(canonical, adapted)
        self.assertEqual(original, json.loads(S.CANONICAL_SCHEMA.read_text(encoding="utf-8")))
        adapted["properties"]["target_kind"]["enum"].clear()
        self.assertEqual(["entity", "event"], S.presentation_model_schema()["properties"]["target_kind"]["enum"])


if __name__ == "__main__":
    unittest.main()
