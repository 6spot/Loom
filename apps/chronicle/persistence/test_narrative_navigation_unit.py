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
        entry = self.prose["entry_points"][0]
        self.prose["navigation"] = [{"label": "汉末的一段历史", "first_paragraph_id": "n0", "last_paragraph_id": "n1",
            "items": [{key: entry[key] for key in ("paragraph_id", "label", "reason")}]}]

    def test_reviewed_range_maps_to_published_ids_without_changing_states(self):
        original = copy.deepcopy(self.prose)
        pub = contract.compile_publication(self.context, self.facts, self.prose)
        navigation = public_navigation(pub)
        self.assertEqual(original, self.prose)
        self.assertEqual((0, 1), (navigation[0]["start"], navigation[0]["end"]))
        self.assertEqual("汉末的一段历史", navigation[0]["label"])
        self.assertEqual(pub["paragraphs"][0]["id"], navigation[0]["items"][0]["paragraph_id"])
        self.assertEqual("major", navigation[0]["items"][0]["importance"])
        self.assertEqual("江东局势", navigation[0]["items"][0]["label"])
        self.assertEqual(["p0", "p1"], [p["phase_id"] for p in pub["paragraphs"]])
        self.prose["navigation"][0]["label"] = "已审核的另一个区间名称"
        self.assertNotEqual(pub["publication_version"], contract.compile_publication(self.context, self.facts, self.prose)["publication_version"])

    def test_incomplete_overlapping_reordered_or_foreign_navigation_is_rejected(self):
        section = self.prose["navigation"][0]
        first = section["items"][0]
        def node(paragraph_id):
            return {**first, "paragraph_id": paragraph_id}
        bad = [
            ([{**section, "first_paragraph_id": "n1"}], "without gaps"),
            ([{**section, "last_paragraph_id": "n0"}], "omit the end"),
            ([section, section], "without gaps"),
            ([{**section, "last_paragraph_id": "foreign"}], "without gaps"),
            ([{**section, "items": [node("foreign")]}], "ordered paragraphs"),
            ([{**section, "items": [node("n0"), node("n0")]}], "ordered paragraphs"),
            ([{**section, "items": []}], "curated entry"),
            ([{**section, "items": [node("n0"), node("n1")]}], "only use curated"),
            ([{**section, "label": "  "}], "labels must not be blank"),
            ([{**section, "items": [{**node("n0"), "reason": "  "}]}], "selection reason"),
        ]
        for sections, message in bad:
            with self.subTest(sections=sections), self.assertRaisesRegex(PersistenceError, message):
                validate_navigation(sections, self.prose["paragraphs"], self.prose["entry_points"])
        with self.assertRaisesRegex(PersistenceError, "ordered paragraphs"):
            validate_navigation([{**section, "items": [node("n1"), node("n0")]}],
                                self.prose["paragraphs"], [node("n0"), node("n1")])

    def test_axis_names_and_reasons_cannot_fork_the_selected_entry(self):
        for key in ("label", "reason"):
            prose = copy.deepcopy(self.prose)
            prose["navigation"][0]["items"][0][key] = "另一份未经入口审核的内容"
            with self.subTest(key=key), self.assertRaisesRegex(PersistenceError, "must match the curated entry"):
                contract.validate_prose(prose, self.context, self.facts)

    def test_intervals_and_whole_publications_may_have_no_selected_event(self):
        self.prose["navigation"] = [
            {**self.prose["navigation"][0], "last_paragraph_id": "n0"},
            {"label": None, "first_paragraph_id": "n1", "last_paragraph_id": "n1", "items": []},
        ]
        pub = contract.compile_publication(self.context, self.facts, self.prose)
        self.assertEqual([], public_navigation(pub)[1]["items"])
        self.assertIsNone(public_navigation(pub)[1]["label"])
        self.prose["entry_points"] = []
        self.prose["navigation"][0]["items"] = []
        pub = contract.compile_publication(self.context, self.facts, self.prose)
        self.assertEqual([], pub["entry_points"])
        self.assertEqual(["p0", "p1"], [p["phase_id"] for p in pub["paragraphs"]])
        self.assertTrue(all(not section["items"] for section in public_navigation(pub)))

    def test_placeholder_reading_actions_cannot_be_selected_events(self):
        self.prose.pop("navigation")
        for label in ("从这段读起", "阅读入口", "年代未详"):
            self.prose["entry_points"][0]["label"] = label
            with self.subTest(label=label), self.assertRaisesRegex(PersistenceError, "placeholder"):
                contract.validate_prose(self.prose, self.context, self.facts)

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
        self.assertEqual([None, "198 年", None, "200 年", None], [s["label"] for s in result])
        major = [item["paragraph_id"] for s in result for item in s["items"] if item["importance"] == "major"]
        self.assertEqual(["p1", "p4", "p7"], major)
        self.assertEqual(3, sum(len(s["items"]) for s in result))
        self.assertEqual([], result[1]["items"])
        self.assertEqual([], result[3]["items"])

    def test_old_published_detail_nodes_are_not_promoted_or_relabelled_as_major(self):
        pub = contract.compile_publication(self.context, self.facts, self.prose)
        pub["navigation"][0]["label"] = "年代未详"
        pub["navigation"][0]["items"][0]["label"] = "旧版轴上另写的名称"
        pub["navigation"][0]["items"].append({"paragraph_id": pub["paragraphs"][1]["id"],
                                            "label": "从这段读起", "reason": "旧版占位节点"})
        original = copy.deepcopy(pub)
        result = public_navigation(pub)
        self.assertEqual(original, pub)
        self.assertIsNone(result[0]["label"])
        self.assertEqual(["江东局势"], [item["label"] for item in result[0]["items"]])

    def test_era_is_shown_once_without_inventing_a_month(self):
        pub = {"paragraphs": [{"id": f"p{n}", "group_id": f"g{n}"} for n in range(3)],
               "groups": [{"id": f"g{n}", "year": 208, "period": period, "label": "已审核进展", "first_paragraph_id": f"p{n}", "count": 1}
                          for n, period in enumerate(["建安十三年春", "建安十三年九月（原历）", "建安十三年，月日未详"])],
               "entry_points": [{"paragraph_id": f"p{n}", "label": f"精选发展{n}"} for n in range(3)]}
        result = public_navigation(pub)
        self.assertEqual("建安十三年", result[0]["period"])
        self.assertEqual(["春", "九月（原历）", None], [item["period"] for item in result[0]["items"]])
        pub["entry_points"] = []
        self.assertEqual("建安十三年", public_navigation(pub)[0]["period"])
        self.assertEqual([], public_navigation(pub)[0]["items"])


if __name__ == "__main__":
    unittest.main()
