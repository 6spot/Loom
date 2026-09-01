from __future__ import annotations

import json
import unittest

from chronicle_ingest import RulesV0Extractor, compare_bundle, validate_bundle


RAW = """十三年春正月，公还邺，作玄武池以肄舟师。汉罢三公官，置丞相、御史大夫。夏六月，以公为丞相。
秋七月，公南征刘表。八月，表卒，其子琮代，屯襄阳，刘备屯樊。九月，公到新野，琮遂降，备走夏口。公进军江陵。乃论荆州服从之功，以刘表大将文聘为江夏太守。十二月，孙权为备攻合肥。公至赤壁，与备战，不利。于是大疫，吏士多死者，乃引军还。备遂有荆州、江南诸郡。"""

CONTEXT = {
    "schema": "chronicle.document-context",
    "version": "0.1",
    "source": {"title": "三国志·魏书·武帝纪", "work": "三国志", "author": "陈寿", "language": "lzh"},
    "narrative": {"primary_subject": {"canonical_name": "曹操", "stable_names": ["曹操", "太祖"], "contextual_mentions": ["公"]}},
    "chronology": {"default_era": "建安", "current_era_year": 13, "normalized_year": 208, "source_calendar": "chinese_lunisolar_regnal"},
    "policies": {"do_not_infer_gregorian_month_from_lunisolar_month": True},
}

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["schema_version", "source", "entities", "events", "claims", "warnings"],
    "properties": {
        "schema_version": {"const": "0.1"},
        "source": {"type": "object", "required": ["temp_id", "kind", "title"]},
        "entities": {"type": "array", "minItems": 1},
        "events": {"type": "array", "minItems": 1},
        "claims": {"type": "array", "minItems": 1},
        "warnings": {"type": "array"},
    },
}


class PrototypeTests(unittest.TestCase):
    def test_extracts_known_vertical_slice(self) -> None:
        bundle = RulesV0Extractor(RAW, CONTEXT, "fixture").extract()
        # This reduced unit-test text omits 张憙, so it has 14 rather than the
        # committed fixture's 15 entities. Events and claims are unchanged.
        self.assertEqual(14, len(bundle["entities"]))
        self.assertEqual(12, len(bundle["events"]))
        self.assertEqual(9, len(bundle["claims"]))
        self.assertEqual("曹操被任命为丞相", bundle["events"][0]["title"])
        self.assertEqual("刘备取得荆州、江南诸郡", bundle["events"][-1]["title"])
        self.assertEqual(208, bundle["events"][8]["time"]["normalized"]["year"])
        self.assertNotIn("month", bundle["events"][8]["time"]["normalized"])

    def test_schema_validation_reports_bad_version(self) -> None:
        bundle = RulesV0Extractor(RAW, CONTEXT, "fixture").extract()
        bundle["schema_version"] = "9.9"
        errors = validate_bundle(bundle, SCHEMA)
        self.assertTrue(errors)
        self.assertTrue(any("schema_version" in error for error in errors))

    def test_semantic_comparison_ignores_extraction_method(self) -> None:
        bundle = RulesV0Extractor(RAW, CONTEXT, "fixture").extract()
        expected = json.loads(json.dumps(bundle, ensure_ascii=False))
        expected["source"]["extraction"]["method"] = "human_gold"
        for group in ("entities", "events", "claims"):
            for item in expected[group]:
                item["extraction"]["method"] = "human_gold"
        expected["warnings"] = []
        self.assertEqual([], compare_bundle(bundle, expected))

    def test_comparison_names_missing_event(self) -> None:
        bundle = RulesV0Extractor(RAW, CONTEXT, "fixture").extract()
        expected = json.loads(json.dumps(bundle, ensure_ascii=False))
        bundle["events"] = bundle["events"][:-1]
        mismatches = compare_bundle(bundle, expected)
        self.assertIn("events: missing 刘备取得荆州、江南诸郡", mismatches)


if __name__ == "__main__":
    unittest.main()
