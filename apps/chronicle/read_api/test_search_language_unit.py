"""Glyph conversion helps discovery without changing identity or source evidence."""
import copy
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
for path in (HERE.parent / "persistence", HERE):
    sys.path.insert(0, str(path))

from read_common import display_surface, entity_display, event_display
from search import _entity_result, _match


class SearchLanguageTests(unittest.TestCase):
    def test_queries_match_across_glyphs_and_keep_original_match_provenance(self):
        rows = [{"canonical_id": "person-one", "bundle": "source", "ref": "entity-ref",
                 "source_title": "原始史料", "payload": {"canonical_name": "劉備", "type": "person", "aliases": ["玄德"]}}]
        before = copy.deepcopy(rows)
        simplified = _entity_result("person-one", rows, "刘备", set())
        traditional = _entity_result("person-one", rows, "劉備", set())
        self.assertEqual(simplified, traditional)
        self.assertEqual(before, rows)
        self.assertEqual("刘备", simplified["display"]["name"])
        source_match = next(item for item in simplified["match"]["matched_surfaces"] if item["field"] == "entity.canonical_name")
        self.assertEqual("劉備", source_match["value"])
        other = _entity_result("person-two", rows, "刘备", {"person-two"})
        self.assertNotEqual(simplified["canonical_id"], other["canonical_id"])
        self.assertTrue(other["identity_uncertain"])

    def test_rank_classes_and_unrelated_source_surface_selection_are_preserved(self):
        self.assertEqual((0, "exact"), _match("赤壁之戰", "赤壁之战", exact_rank=0))
        self.assertEqual((2, "prefix"), _match("劉備入蜀", "刘备", exact_rank=1))
        self.assertEqual((3, "substring"), _match("會見劉備", "刘备", exact_rank=1))
        self.assertEqual((4, "substring"), _match("會見劉備", "刘备", exact_rank=1, secondary=True))
        self.assertEqual("劉備", display_surface(["劉備"]))
        self.assertEqual("赤壁之战", event_display([{"title": "赤壁之戰"}])["title"])
        self.assertIsNone(entity_display([])["name"])


if __name__ == "__main__":
    unittest.main()
