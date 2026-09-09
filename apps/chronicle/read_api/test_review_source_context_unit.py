"""Unit tests for the T10 shared source reader (no PostgreSQL).

Covers BOM/CRLF/non-BMP decoding, duplicate-quote occurrence handling,
cross-chapter/cross-revision same-text discrimination, window/chapter
paging bounds, opaque cursor scope binding, and frozen-member collection.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
for candidate in (str(HERE), str(PERSISTENCE)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import source_context as SC  # noqa: E402


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RevisionReadTests(unittest.TestCase):
    def test_bom_crlf_stripped_before_code_point_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = "﻿第一行\r\n第二行\r第三行\n".encode("utf-8")
            key = "documents/d/r.txt"
            dest = Path(tmp) / key
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
            text = SC.read_revision_text(
                tmp, key, hashlib.sha256(raw).hexdigest()
            )
            self.assertEqual(text, "第一行\n第二行\n第三行\n")
            # Code-point slice lands on the decoded text, not raw bytes.
            self.assertEqual(text[0:3], "第一行")

    def test_non_bmp_counts_as_single_code_point(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = "甲𠀋乙".encode("utf-8")
            key = "documents/d/r.txt"
            dest = Path(tmp) / key
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
            text = SC.read_revision_text(
                tmp, key, hashlib.sha256(raw).hexdigest()
            )
            self.assertEqual(len(text), 3)
            window = SC.window_for(text, 1, 2, radius=1)
            self.assertEqual(window["text"], "甲𠀋乙")
            highlighted = [seg for seg in window["segments"] if seg["highlight"]]
            self.assertEqual(highlighted, [{"text": "𠀋", "highlight": True}])

    def test_hash_drift_never_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = "舊版文字".encode("utf-8")
            key = "documents/d/r.txt"
            dest = Path(tmp) / key
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes("新版文字".encode("utf-8"))
            with self.assertRaises(SC.SourceMismatch):
                SC.read_revision_text(tmp, key, hashlib.sha256(raw).hexdigest())

    def test_missing_file_is_unavailable_not_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SC.SourceUnavailable):
                SC.read_revision_text(tmp, "documents/d/gone.txt", "0" * 64)


class AnchorVerifyTests(unittest.TestCase):
    TEXT = "曹操至，曹操去。曹操留。"

    def _anchor(self, occurrence: int) -> dict:
        positions: list[int] = []
        start = 0
        while True:
            found = self.TEXT.find("曹操", start)
            if found < 0:
                break
            positions.append(found)
            start = found + 1
        start = positions[occurrence - 1]
        return {
            "anchor_id": f"anc_{occurrence}",
            "start": start,
            "end": start + 2,
            "quote": "曹操",
            "quote_sha256": _sha_text("曹操"),
            "occurrence": occurrence,
        }

    def test_repeated_quote_resolves_by_occurrence(self) -> None:
        second = self._anchor(2)
        self.assertEqual((second["start"], second["end"]), (4, 6))
        SC.verify_anchor(second, self.TEXT)

    def test_wrong_range_is_mismatch(self) -> None:
        anchor = self._anchor(1)
        anchor["start"], anchor["end"] = 1, 3  # text "操至" != quote "曹操"
        with self.assertRaises(SC.SourceMismatch):
            SC.verify_anchor(anchor, self.TEXT)

    def test_same_text_other_revision_is_not_substituted(self) -> None:
        anchor = self._anchor(1)
        other = "前言。" + self.TEXT  # same quote, shifted location
        with self.assertRaises(SC.SourceMismatch):
            SC.verify_anchor(anchor, other)

    def test_cross_chapter_same_text_needs_exact_range(self) -> None:
        anchor_a = {"start": 0, "end": 2, "quote": "曹操", "quote_sha256": _sha_text("曹操")}
        SC.verify_anchor(anchor_a, self.TEXT)
        anchor_b = dict(anchor_a, start=11, end=13)
        with self.assertRaises(SC.SourceMismatch):
            SC.verify_anchor(anchor_b, self.TEXT)


class PagingTests(unittest.TestCase):
    def test_window_defaults_to_400_each_side(self) -> None:
        text = "a" * 500 + "曹操" + "b" * 500
        window = SC.window_for(text, 500, 502)
        self.assertEqual(window["slice_start"], 100)
        self.assertEqual(window["slice_end"], 902)
        self.assertEqual(len(window["text"]), 802)
        highlighted = "".join(seg["text"] for seg in window["segments"] if seg["highlight"])
        self.assertEqual(highlighted, "曹操")

    def test_window_clamps_at_chapter_edges(self) -> None:
        text = "曹操" + "x" * 10
        window = SC.window_for(text, 0, 2)
        self.assertEqual((window["slice_start"], window["slice_end"]), (0, 12))

    def test_chapter_pages_are_bounded_and_chained(self) -> None:
        text = "字" * 40000
        first = SC.chapter_page_for(text, 0)
        self.assertEqual((first["slice_start"], first["slice_end"]), (0, 16000))
        self.assertTrue(first["has_more"])
        second = SC.chapter_page_for(text, first["slice_end"])
        self.assertEqual((second["slice_start"], second["slice_end"]), (16000, 32000))
        self.assertTrue(second["has_more"])
        last = SC.chapter_page_for(text, 32000)
        self.assertFalse(last["has_more"])
        self.assertEqual(last["slice_end"], 40000)

    def test_chapter_page_highlights_anchor_when_visible(self) -> None:
        text = "甲乙曹操丙丁"
        anchor = {"start": 2, "end": 4, "quote": "曹操", "quote_sha256": _sha_text("曹操")}
        page = SC.chapter_page_for(text, 0, limit=16000, anchor=anchor)
        highlighted = "".join(seg["text"] for seg in page["segments"] if seg["highlight"])
        self.assertEqual(highlighted, "曹操")

    def test_chapter_cursor_past_end_is_400(self) -> None:
        with self.assertRaises(SC.BadCursor):
            SC.chapter_page_for("短", 99)


class CursorTests(unittest.TestCase):
    def test_context_cursor_binds_review_and_group(self) -> None:
        token = SC.encode_context_cursor(review_id="r1", group_id="g1", offset=50)
        self.assertEqual(SC.decode_context_cursor(token, review_id="r1", group_id="g1"), 50)
        with self.assertRaises(SC.BadCursor):
            SC.decode_context_cursor(token, review_id="r2", group_id="g1")
        with self.assertRaises(SC.BadCursor):
            SC.decode_context_cursor(token, review_id="r1", group_id="g2")
        with self.assertRaises(SC.BadCursor):
            SC.decode_context_cursor("not-a-cursor", review_id="r1", group_id="g1")

    def test_source_cursor_binds_review_anchor_view(self) -> None:
        token = SC.encode_source_cursor(
            review_id="r1", anchor_id="anc_1", view="chapter", offset=16000
        )
        self.assertEqual(
            SC.decode_source_cursor(
                token, review_id="r1", anchor_id="anc_1", view="chapter"
            ),
            16000,
        )
        with self.assertRaises(SC.BadCursor):
            SC.decode_source_cursor(
                token, review_id="r1", anchor_id="anc_2", view="chapter"
            )
        with self.assertRaises(SC.BadCursor):
            SC.decode_source_cursor(
                token, review_id="r1", anchor_id="anc_1", view="window"
            )


class FrozenMemberTests(unittest.TestCase):
    def test_chapter_pair_collects_both_ends_once(self) -> None:
        payload = {
            "review_mode": "chapter_pair",
            "members": [
                {
                    "candidate_key": "k1",
                    "left": {"bundle": "bund", "ref": "ent_000001"},
                    "right": {"bundle": "bund", "ref": "ent_001001"},
                }
            ],
        }
        self.assertEqual(
            SC.frozen_member_refs(payload),
            [
                {"bundle": "bund", "ref": "ent_000001"},
                {"bundle": "bund", "ref": "ent_001001"},
            ],
        )

    def test_batch_collects_every_member_not_first_only(self) -> None:
        payload = {
            "review_mode": "published_batch",
            "members": [
                {
                    "candidate_key": "k1",
                    "left": {"bundle": "pub", "ref": "ent_p1"},
                    "right": {"bundle": "new", "ref": "ent_000001"},
                },
                {
                    "candidate_key": "k2",
                    "left": {"bundle": "pub", "ref": "ent_p1"},
                    "right": {"bundle": "new", "ref": "ent_001001"},
                },
            ],
            "groups": [
                {
                    "review_group_id": "rg_1",
                    "members": [
                        {
                            "candidate_key": "k1",
                            "left": {"bundle": "pub", "ref": "ent_p1"},
                            "right": {"bundle": "new", "ref": "ent_000001"},
                        }
                    ],
                },
                {
                    "review_group_id": "rg_2",
                    "members": [
                        {
                            "candidate_key": "k2",
                            "left": {"bundle": "pub", "ref": "ent_p1"},
                            "right": {"bundle": "new", "ref": "ent_001001"},
                        }
                    ],
                },
            ],
        }
        refs = SC.frozen_member_refs(payload)
        self.assertEqual(len(refs), 3)
        self.assertIn({"bundle": "new", "ref": "ent_001001"}, refs)
        self.assertEqual(
            SC.group_member_refs(payload, "rg_2"),
            [
                {"bundle": "new", "ref": "ent_001001"},
                {"bundle": "pub", "ref": "ent_p1"},
            ],
        )
        self.assertIsNone(SC.group_member_refs(payload, "rg_missing"))

    def test_legacy_payload_falls_back_to_left_right(self) -> None:
        payload = {
            "left": {"bundle": "left", "ref": "ent_001"},
            "right": {"bundle": "right", "ref": "ent_001"},
        }
        self.assertEqual(len(SC.frozen_member_refs(payload)), 2)

    def test_context_ids_are_stable_per_review_member(self) -> None:
        first = SC.context_id_for("r1", "bund", "ent_000001")
        self.assertEqual(first, SC.context_id_for("r1", "bund", "ent_000001"))
        self.assertNotEqual(first, SC.context_id_for("r1", "bund", "ent_001001"))
        self.assertNotEqual(first, SC.context_id_for("r2", "bund", "ent_000001"))


if __name__ == "__main__":
    unittest.main()
