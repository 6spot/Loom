"""Navigation is a reviewed subset; unknown dates and source bytes stay intact."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import narrative_contract as contract
from common import PersistenceError
from narrative_navigation import public_navigation, validate_navigation
from test_narrative_contract import context_fixture, drafts


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.context = context_fixture()
        self.facts, self.prose = drafts(self.context)
        self.prose["navigation"] = [{"label": "汉末的一段历史", "first_paragraph_id": "n0", "last_paragraph_id": "n1",
            "items": [{"paragraph_id": "n0", "label": "阅读入口", "reason": "从这段已审核叙事开始。"}]}]

    def test_reviewed_range_maps_to_published_ids_without_changing_states(self):
        original = copy.deepcopy(self.prose)
        pub = contract.compile_publication(self.context, self.facts, self.prose)
        navigation = public_navigation(pub)
        self.assertEqual(original, self.prose)
        self.assertEqual((0, 1), (navigation[0]["start"], navigation[0]["end"]))
        self.assertEqual("汉末的一段历史", navigation[0]["label"])
        self.assertEqual(pub["paragraphs"][0]["id"], navigation[0]["items"][0]["paragraph_id"])
        self.assertEqual("major", navigation[0]["items"][0]["importance"])
        self.assertEqual("阅读入口", navigation[0]["items"][0]["label"])
        self.assertEqual(["p0", "p1"], [p["phase_id"] for p in pub["paragraphs"]])
        self.prose["navigation"][0]["label"] = "已审核的另一个区间名称"
        self.assertNotEqual(pub["publication_version"], contract.compile_publication(self.context, self.facts, self.prose)["publication_version"])

    def test_incomplete_overlapping_reordered_or_foreign_navigation_is_rejected(self):
        section = self.prose["navigation"][0]
        def node(paragraph_id):
            return {"paragraph_id": paragraph_id, "label": "有据进展", "reason": "这段提供阅读定位。"}
        bad = [
            ([{**section, "first_paragraph_id": "n1"}], "without gaps"),
            ([{**section, "last_paragraph_id": "n0"}], "omit the end"),
            ([section, section], "without gaps"),
            ([{**section, "last_paragraph_id": "foreign"}], "without gaps"),
            ([{**section, "items": [node("foreign")]}], "ordered paragraphs"),
            ([{**section, "items": [node("n1"), node("n0")]}], "ordered paragraphs"),
            ([{**section, "items": [node("n0"), node("n0")]}], "ordered paragraphs"),
            ([{**section, "items": [node("n1")]}], "curated entry"),
            ([{**section, "label": "  "}], "labels must not be blank"),
            ([{**section, "items": [{**node("n0"), "reason": "  "}]}], "selection reason"),
        ]
        for sections, message in bad:
            with self.subTest(sections=sections), self.assertRaisesRegex(PersistenceError, message):
                validate_navigation(sections, self.prose["paragraphs"], self.prose["entry_points"])

    def test_legacy_unknown_runs_are_separate_and_do_not_become_one_node_per_phase(self):
        years = [None, None, 198, None, None, 200, None, None]
        pub = {"paragraphs": [{"id": f"p{n}", "group_id": f"g{n}"} for n in range(8)],
               "groups": [{"id": f"g{n}", "year": year, "period": None, "label": f"内部阶段{n}", "first_paragraph_id": f"p{n}", "count": 1}
                          for n, year in enumerate(years)],
               "entry_points": [{"paragraph_id": f"p{n}", "label": f"重要入口{n}"} for n in (1, 4, 7)]}
        original = copy.deepcopy(pub)
        result = public_navigation(pub)
        self.assertEqual(original, pub)
        self.assertEqual([(0, 1), (2, 2), (3, 4), (5, 5), (6, 7)], [(s["start"], s["end"]) for s in result])
        self.assertEqual(["年代未详", "198 年", "年代未详", "200 年", "年代未详"], [s["label"] for s in result])
        major = [item["paragraph_id"] for s in result for item in s["items"] if item["importance"] == "major"]
        self.assertEqual(["p1", "p4", "p7"], major)
        self.assertEqual(5, sum(len(s["items"]) for s in result))

    def test_era_is_shown_once_without_inventing_a_month(self):
        pub = {"paragraphs": [{"id": f"p{n}", "group_id": f"g{n}"} for n in range(3)],
               "groups": [{"id": f"g{n}", "year": 208, "period": period, "label": "已审核进展", "first_paragraph_id": f"p{n}", "count": 1}
                          for n, period in enumerate(["建安十三年春", "建安十三年九月（原历）", "建安十三年，月日未详"])],
               "entry_points": []}
        result = public_navigation(pub)
        self.assertEqual("建安十三年", result[0]["period"])
        self.assertEqual(["春", "九月（原历）", "月日未详"], [item["period"] for item in result[0]["items"]])


if __name__ == "__main__":
    unittest.main()
