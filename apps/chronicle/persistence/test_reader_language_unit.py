"""Reader orthography must never change original-source evidence or identity."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chapter_production import translation_document
from reader_language import history_display, narrative_text


class ReaderLanguageTests(unittest.TestCase):
    def test_malformed_model_shapes_survive_for_the_schema_validator_to_explain(self):
        for candidate in ({"phases": None, "paragraphs": "bad", "navigation": 7},
                          {"conclusions": [{"evidence": None}], "paragraphs": [None, {"segments": None}]}):
            self.assertEqual(candidate, narrative_text(candidate))

    def test_full_translation_is_simplified_before_blocks_are_linked(self):
        raw = "孫權召集部屬商議。\n\n周瑜領軍抵達江陵。"
        translation = translation_document(raw)
        self.assertEqual("zh-CN", translation["language"])
        self.assertEqual([{"block_id": "tr_001", "text": "孙权召集部属商议。"},
                          {"block_id": "tr_002", "text": "周瑜领军抵达江陵。"}], translation["blocks"])
        self.assertIn("孫權", raw)

    def test_editorial_normalization_keeps_all_references_and_source_quotes(self):
        candidate = {"phases": [{"id": "phase_孫", "label": "迎喪", "period": None}],
            "conclusions": [{"id": "f_孫", "subject_id": "entity_孫", "text": "孫權的記載", "value": "奮武校尉",
                "evidence": [{"id": "e_孫", "note": "本傳記載", "quote": "瑜迎喪"}]}],
            "paragraphs": [{"id": "n_孫", "segments": [{"text": "赤壁之戰以後，孫權追念周瑜。", "event_text": "赤壁之戰", "conclusion_ids": ["f_孫"]}]}]}
        before = copy.deepcopy(candidate)
        result = narrative_text(candidate)
        self.assertEqual(before, candidate)
        self.assertEqual("迎丧", result["phases"][0]["label"])
        self.assertEqual("entity_孫", result["conclusions"][0]["subject_id"])
        self.assertEqual("瑜迎喪", result["conclusions"][0]["evidence"][0]["quote"])
        segment = result["paragraphs"][0]["segments"][0]
        self.assertIn(segment["event_text"], segment["text"])
        self.assertEqual(["f_孫"], segment["conclusion_ids"])
        self.assertEqual(result, narrative_text(result))

    def test_public_projection_changes_glyphs_without_rewriting_the_publication(self):
        pub = {"publication_version": "a" * 64, "paragraphs": [{"id": "hp_123", "phase_id": "p1", "segments": [],
            "entities": [{"id": "person-id", "name": "劉備", "states": [{"id": "s1", "value": "左將軍", "certainty": "uncertain", "reason": "任職時段未詳"}]}]}],
            "evidence": {"e1": {"quote": "備領荊州", "start": 9, "end": 13, "anchor_id": "原anchor"}},
            "groups": [{"id": "g1", "label": "荊州", "period": None}]}
        before = copy.deepcopy(pub)
        result = history_display(pub)
        self.assertEqual(before, pub)
        self.assertEqual(before["evidence"], result["evidence"])
        entity = result["paragraphs"][0]["entities"][0]
        self.assertEqual(("person-id", "刘备", "左将军", "uncertain"), (entity["id"], entity["name"], entity["states"][0]["value"], entity["states"][0]["certainty"]))


if __name__ == "__main__":
    unittest.main()
