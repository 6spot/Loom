"""C2-R3-D01 person-state case corpus contracts (offline, read-only).

Verifies the third-round case index under ``apps/chronicle/corpus/third-round``:

* at least 16 cases with real/synthetic labels, allowed/forbidden display results
  and a per-item expectation of person/dimension/phase/operation/qualification/
  certainty/reason/attribution;
* every real reference relocates into the frozen first-round file by raw-byte
  SHA-256, strict UTF-8 / NFC text, exact Unicode code-point ``[start,end)`` and
  the declared 1-based occurrence, with no first-round source mutated or copied;
* each expected ``surface`` actually occurs in its referenced quote, so a case
  description that disagrees with the frozen text fails the check;
* ancestor/father offices, action roles and future titles never enter the
  person's current identity;
* synthetic entries carry ``synthetic=true``, never stand in for a source
  observation, and the whole bundle stays marked as human content review rather
  than a real model or backend result.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIRST_ROUND = HERE / "first-round"
THIRD_ROUND = HERE / "third-round"
CASES = THIRD_ROUND / "cases.json"

MAX_VERBATIM_RUN = 300

FROZEN_SOURCES = {
    "xianzhu-liubei": {
        "file": "sources/sanguozhi-032-xianzhu-liubei.txt",
        "sha256": "ea40a7087560fe9e693e6f81cb7d1689704f888a40b5b8a8bf7169ec272994e8",
        "chars": 12572,
    },
    "zhou-yu": {
        "file": "sources/sanguozhi-054-zhou-yu.txt",
        "sha256": "63db082c4e763be3b56c87cb56e2bed904af5325e9a498b07d932d3b5af1f43e",
        "chars": 5018,
    },
    "lu-su": {
        "file": "sources/sanguozhi-054-lu-su.txt",
        "sha256": "1550e1735f44eda7adb9bf27f4ed2cbc9c2185baf6634400140cd52ac312553d",
        "chars": 3583,
    },
    "zztj-065": {
        "file": "sources/zizhi-tongjian-065-quan.txt",
        "sha256": "c7f80c6baff73a0caa0bbf365117b9ae91892da590ab3830392deb9bcb46fd38",
        "chars": 10680,
    },
}

REAL_CATEGORIES = {
    "appointment",
    "concurrent-office",
    "cross-chapter-concurrent",
    "event-role",
    "transfer",
    "resignation",
    "ancestor-office",
    "annotation-attribution",
    "commentary-attribution",
}

SYNTHETIC_CATEGORIES = {
    "same-year-order-unknown",
    "cross-chapter-retrospective",
    "re-appointment-after-end",
    "future-title",
    "empty-state",
    "opposing-source",
}

REVERSE_ORDER_CATEGORIES = {"ancestor-office", "event-role", "future-title", "same-year-order-unknown"}


def _load() -> dict:
    return json.loads(CASES.read_text(encoding="utf-8"))


def _source_text(key: str) -> str:
    return (FIRST_ROUND / FROZEN_SOURCES[key]["file"]).read_text(encoding="utf-8")


def relocate(ref: dict) -> None:
    """Strictly relocate one reference; raise AssertionError when inconsistent."""
    key = ref["source_key"]
    frozen = FROZEN_SOURCES[key]
    raw = (FIRST_ROUND / frozen["file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == frozen["sha256"], f"first-round source drifted: {key}"
    assert ref["file"] == frozen["file"], f"ref path mismatch: {ref}"
    assert ref["sha256"] == frozen["sha256"], f"ref sha mismatch: {ref}"
    assert ref.get("attribution"), f"ref missing source attribution: {ref}"
    text = raw.decode("utf-8")
    assert unicodedata.normalize("NFC", text) == text, f"source not NFC-stable: {key}"
    start, end = ref["start"], ref["end"]
    assert 0 <= start < end <= len(text), f"range out of bounds: {ref}"
    assert text[start:end] == ref["quote"], f"quote != frozen text at [{start},{end}): {ref}"
    occurrence = text[:start].count(ref["quote"]) + 1
    assert occurrence == ref["occurrence"], f"occurrence mismatch: {ref}"


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def recommendation_violations(bundle: dict) -> list:
    """Return (case_id, index) for recommendation/posthumous items breaking the contract.

    ``person-state-reading.md`` §3.2 requires recommendations and posthumous grants
    to be qualified in-phase observations only: ``operation=attest``, never entering
    the person's current identity, and keeping the recommending actor visible.
    """
    violations = []
    for case in bundle["cases"]:
        for index, item in enumerate(case["expected"]):
            if item.get("qualification") not in ("recommendation", "posthumous"):
                continue
            actor = item.get("actor")
            if (
                item["operation"] != "attest"
                or item["enters_identity"]
                or not actor
                or actor not in item.get("display", "")
            ):
                violations.append((case["id"], index))
    return violations


class BundleTests(unittest.TestCase):
    def test_bundle_shape_counts_and_unique_ids(self) -> None:
        bundle = _load()
        self.assertEqual(bundle["schema"], "chronicle.third-round-person-state-cases")
        self.assertEqual(bundle["pack_id"], "c2-r3-d01-person-state-cases-v1")
        self.assertEqual(bundle["task"], "C2-R3-D01")
        self.assertEqual(bundle["issue"], 617)
        self.assertEqual(bundle["parent_issue"], 550)
        self.assertEqual(bundle["round"], "R3")
        self.assertEqual(bundle["derived_from"], "c2-r1-t02-first-round-v1")
        self.assertEqual(bundle["coordinate_unit"], "unicode_code_point")
        self.assertEqual(bundle["contract"], "apps/chronicle/docs/person-state-reading.md")
        case_ids = [case["id"] for case in bundle["cases"]]
        self.assertEqual(len(case_ids), len(set(case_ids)), "duplicate case id")
        real = [case for case in bundle["cases"] if not case["synthetic"]]
        synthetic = [case for case in bundle["cases"] if case["synthetic"]]
        self.assertGreaterEqual(len(bundle["cases"]), 16)
        self.assertEqual(bundle["real_case_count"], len(real))
        self.assertEqual(bundle["synthetic_case_count"], len(synthetic))
        self.assertGreaterEqual(len(real), 10)
        self.assertGreaterEqual(len(synthetic), 6)

    def test_required_real_and_synthetic_categories(self) -> None:
        bundle = _load()
        real = {case["category"] for case in bundle["cases"] if not case["synthetic"]}
        synthetic = {case["category"] for case in bundle["cases"] if case["synthetic"]}
        self.assertTrue(
            {"appointment", "concurrent-office", "transfer", "resignation", "ancestor-office", "annotation-attribution"}
            <= real,
            sorted(real),
        )
        self.assertTrue(REAL_CATEGORIES <= real, sorted(REAL_CATEGORIES - real))
        self.assertEqual(SYNTHETIC_CATEGORIES, synthetic)

    def test_every_case_has_expectation_forbidden_and_evidence_class(self) -> None:
        bundle = _load()
        for case in bundle["cases"]:
            with self.subTest(case=case["id"]):
                self.assertTrue(case["title"])
                self.assertTrue(case["question"])
                self.assertTrue(case["forbidden"], case["id"])
                self.assertTrue(case["observation"], case["id"])
                self.assertEqual(case["evidence_class"], "human-content-review")
                self.assertIn("synthetic", case)
                for item in case["expected"]:
                    self.assertIn(item["dimension"], {"office", "title", "affiliation", "action_role", "none"})
                    self.assertIn(item["operation"], {"start", "end", "attest"})
                    if item["enters_identity"]:
                        self.assertIn(item["certainty"], {"clear", "uncertain"})
                        self.assertTrue(item["display"])
                        if item["certainty"] == "uncertain":
                            self.assertTrue(item["reason_code"])
                    if item["reason_code"] is not None:
                        self.assertIn(item["reason_code"], bundle["reason_codes"])
                    self.assertTrue(item["attribution"])


class RelocationTests(unittest.TestCase):
    def test_real_references_relocate_into_frozen_first_round(self) -> None:
        bundle = _load()
        for case in bundle["cases"]:
            if case["synthetic"]:
                continue
            with self.subTest(case=case["id"]):
                self.assertTrue(case["refs"], f"real case without refs: {case['id']}")
                for ref in case["refs"]:
                    relocate(ref)

    def test_synthetic_references_are_real_or_empty(self) -> None:
        bundle = _load()
        for case in bundle["cases"]:
            if not case["synthetic"]:
                continue
            with self.subTest(case=case["id"]):
                for ref in case["refs"]:
                    relocate(ref)

    def test_expected_surface_matches_the_quoted_source(self) -> None:
        bundle = _load()
        for case in bundle["cases"]:
            with self.subTest(case=case["id"]):
                for item in case["expected"]:
                    surface = item.get("surface")
                    if surface is None:
                        continue
                    proven_by = item.get("proven_by")
                    self.assertIsInstance(proven_by, int, f"{case['id']} missing proven_by")
                    self.assertLess(proven_by, len(case["refs"]), f"{case['id']} proven_by out of range")
                    quote = case["refs"][proven_by]["quote"]
                    self.assertIn(surface, quote, f"{case['id']} surface not in quoted source: {surface}")

    def test_relocation_check_detects_inconsistent_quotes(self) -> None:
        bundle = _load()
        ref = next(case["refs"][0] for case in bundle["cases"] if case["refs"])
        inconsistent = dict(ref)
        inconsistent["quote"] = ref["quote"] + "（被改动的说明）"
        with self.assertRaises(AssertionError):
            relocate(inconsistent)
        shifted = dict(ref)
        shifted["start"] = ref["start"] + 1
        shifted["end"] = ref["end"] + 1
        with self.assertRaises(AssertionError):
            relocate(shifted)


class IdentityBoundaryTests(unittest.TestCase):
    def test_ancestor_role_and_future_never_enter_current_identity(self) -> None:
        bundle = _load()
        for case in bundle["cases"]:
            if case["category"] not in REVERSE_ORDER_CATEGORIES:
                continue
            with self.subTest(case=case["id"]):
                for item in case["expected"]:
                    self.assertFalse(
                        item["enters_identity"],
                        f"{case['id']} must not assign {item['dimension']}={item['value']} to the subject",
                    )

    def test_affiliation_and_office_items_name_their_subject(self) -> None:
        bundle = _load()
        for case in bundle["cases"]:
            for item in case["expected"]:
                if item["enters_identity"]:
                    self.assertIsNotNone(item.get("value") or item.get("target"), case["id"])

    def test_empty_state_case_has_no_fabricated_identity(self) -> None:
        bundle = _load()
        empties = [case for case in bundle["cases"] if case["category"] == "empty-state"]
        self.assertTrue(empties)
        for case in empties:
            self.assertTrue(case["empty_state"])
            self.assertEqual(case["expected"], [])
            self.assertEqual(case["refs"], [])


class RecommendationInvariantTests(unittest.TestCase):
    def test_recommendations_are_attested_observations_not_current_appointments(self) -> None:
        bundle = _load()
        self.assertEqual(recommendation_violations(bundle), [])
        recommended = [
            (case["id"], item["value"])
            for case in bundle["cases"]
            for item in case["expected"]
            if item.get("qualification") == "recommendation"
        ]
        self.assertGreaterEqual(len(recommended), 3, recommended)

    def test_recommendation_invariant_detects_a_current_appointment(self) -> None:
        bundle = _load()
        target = next(
            item
            for case in bundle["cases"]
            for item in case["expected"]
            if item.get("qualification") == "recommendation"
        )
        self.assertEqual(recommendation_violations(bundle), [])
        target["operation"] = "start"
        target["enters_identity"] = True
        self.assertTrue(recommendation_violations(bundle))


class EvidenceClassTests(unittest.TestCase):
    def test_bundle_never_presents_human_expectation_as_model_output(self) -> None:
        bundle = _load()
        for case in bundle["cases"]:
            with self.subTest(case=case["id"]):
                self.assertEqual(case["evidence_class"], "human-content-review")
                lowered = {key.lower() for key in case}
                for banned in ("model_output", "model_result", "model_verified", "generated_by_model", "live_backend"):
                    self.assertNotIn(banned, lowered)
        self.assertNotIn("model_output", bundle)
        self.assertNotIn("model_result", bundle)

    def test_synthetic_entries_never_claim_a_reliable_identity(self) -> None:
        bundle = _load()
        for case in bundle["cases"]:
            if not case["synthetic"]:
                continue
            with self.subTest(case=case["id"]):
                for item in case["expected"]:
                    self.assertFalse(item["enters_identity"] and item["certainty"] == "clear")


class FirstRoundPreservationTests(unittest.TestCase):
    def test_first_round_sources_and_cases_are_untouched(self) -> None:
        for key, frozen in FROZEN_SOURCES.items():
            raw = (FIRST_ROUND / frozen["file"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), frozen["sha256"], key)
            self.assertEqual(len(raw.decode("utf-8")), frozen["chars"], key)
        first_round_cases = json.loads((FIRST_ROUND / "cases.json").read_text(encoding="utf-8"))
        real = [case for case in first_round_cases["cases"] if not case.get("synthetic")]
        synthetic = [case for case in first_round_cases["cases"] if case.get("synthetic")]
        self.assertEqual(len(real), 13)
        self.assertEqual(len(synthetic), 1)

    def test_third_round_does_not_copy_a_frozen_chapter(self) -> None:
        probe = _load()
        for name in ("README.md", "walkthrough.md"):
            probe.setdefault("docs", []).append((THIRD_ROUND / name).read_text(encoding="utf-8"))
        strings = [s for s in _strings(probe) if len(s) >= MAX_VERBATIM_RUN]
        for key in FROZEN_SOURCES:
            text = _source_text(key)
            for value in strings:
                self.assertNotIn(value, text, f"copied a long verbatim run from {key}")
        for case in _load()["cases"]:
            for ref in case["refs"]:
                self.assertLessEqual(len(ref["quote"]), 120, f"quote unexpectedly long: {case['id']}")
        third_round_files = sorted(THIRD_ROUND.rglob("*"))
        self.assertFalse([path for path in third_round_files if path.suffix == ".txt"], "chapter copy under third-round")


if __name__ == "__main__":
    unittest.main()
