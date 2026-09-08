"""Unit tests for Chronicle C2-R1-T03 chapter planning (no PostgreSQL).

Covers the frozen contract from chapter-production.md section 2 using
the T01 model (chapter_contract) and the frozen T02 corpus
(corpus/first-round): txt single-chapter immunity to inner letter
titles, the exact three Sanguozhi chapters with full-text coverage,
preface/blank/nested-heading range reconstruction, BOM/CRLF/extended
CJK code-point coordinates, plan determinism/hashes, whole-chapter
over-limit rejection without losing the source, and structural
fail-closed cases. Pure functions only: no DB, network, or model calls.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import chapter_contract as C  # noqa: E402
import chapter_plan as P  # noqa: E402
from common import PersistenceError, canonical_json_bytes  # noqa: E402

FIRST_ROUND = HERE.parent / "corpus" / "first-round"
INGEST = FIRST_ROUND / "ingest"
SOURCES = FIRST_ROUND / "sources"
REJECTED = FIRST_ROUND / "rejected"


def _locator(text: str, revision_id: str = "rev_t03_test_001") -> dict:
    return {
        "revision_id": revision_id,
        "source_sha256": hashlib.sha256(b"raw:" + text.encode("utf-8")).hexdigest(),
        "normalized_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def _read(name: str) -> str:
    return (INGEST / name).read_bytes().decode("utf-8")


def _assert_tiles(test: unittest.TestCase, plan: dict, text: str) -> None:
    chapters = plan["chapters"]
    test.assertEqual(chapters[0]["start"], 0)
    cursor = 0
    for chapter in chapters:
        test.assertEqual(chapter["start"], cursor)
        test.assertLess(chapter["start"], chapter["end"])
        assembled = "".join(
            text[block["start"]:block["end"]] for block in chapter["blocks"]
        )
        test.assertEqual(assembled, text[chapter["start"]:chapter["end"]])
        for block in chapter["blocks"]:
            test.assertEqual(
                block["content_sha256"],
                hashlib.sha256(
                    text[block["start"]:block["end"]].encode("utf-8")
                ).hexdigest(),
            )
        required = set(chapter["required_block_ids"])
        body = {
            block["block_id"]
            for block in chapter["blocks"]
            if block["kind"] == "body"
            and text[block["start"]:block["end"]].strip()
        }
        test.assertEqual(required, body)
        test.assertTrue(required)
        cursor = chapter["end"]
    test.assertEqual(cursor, len(text))


class TxtSingleChapterTests(unittest.TestCase):
    def test_zhuge_letter_titles_do_not_split(self) -> None:
        # Regression: a whole-biography txt whose inner letter titles and
        # classic chapter/volume patterns would trip C1 structure
        # detection must still plan as exactly one chapter.
        text = "\n".join(
            [
                "諸葛亮字孔明，琅邪陽都人也。",
                "出師表",
                "先帝創業未半而中道崩殂。",
                "後出師表",
                "先帝慮漢賊不兩立，王業不偏安。",
                "第十三回 孔明借東風",
                "卷第一",
                "武帝紀第一",
                "諸葛亮傳第二十五",
                "## 假裝是章節的行",
                "〈裴松之注：此條存疑，當考。〉",
                "建興十二年，亮卒於五丈原。",
            ]
        )
        plan = P.plan_chapters(text, _locator(text), "zhuge-liang-quan.txt")
        self.assertEqual(plan["chapter_count"], 1)
        chapter = plan["chapters"][0]
        self.assertEqual((chapter["start"], chapter["end"]), (0, len(text)))
        self.assertEqual(chapter["content_sha256"], P.sha256_text(text))
        _assert_tiles(self, plan, text)
        # Every prose line stays body content under translation coverage;
        # no heading interpretation happens in the txt entry.
        kinds = {block["kind"] for block in chapter["blocks"]}
        self.assertNotIn("heading", kinds)

    def test_txt_ignores_hash_lines_entirely(self) -> None:
        text = "# 不是書名\n\n正文第一段。\n\n# 也不是書名\n\n正文第二段。\n"
        plan = P.plan_chapters(text, _locator(text), "notes.txt")
        self.assertEqual(plan["chapter_count"], 1)
        self.assertEqual(plan["chapters"][0]["title"], "notes")
        _assert_tiles(self, plan, text)

    def test_txt_title_is_filename_stem(self) -> None:
        text = "先主姓劉，諱備，字玄德。\n"
        plan = P.plan_chapters(
            text, _locator(text), "sanguozhi-032-xianzhu-liubei.txt"
        )
        self.assertEqual(
            plan["chapters"][0]["title"], "sanguozhi-032-xianzhu-liubei"
        )


class SanguozhiThreeChapterTests(unittest.TestCase):
    def test_exactly_three_chapters_with_full_text(self) -> None:
        text = _read("sanguozhi-three-chapters.md")
        plan = P.plan_chapters(
            text, _locator(text, "rev_sanguozhi_001"), "sanguozhi-three-chapters.md"
        )
        self.assertEqual(plan["chapter_count"], 3)
        self.assertEqual(
            [c["title"] for c in plan["chapters"]],
            ["蜀書·先主傳", "吳書·周瑜傳", "吳書·魯肅傳"],
        )
        self.assertEqual(
            [c["chapter_index"] for c in plan["chapters"]], [0, 1, 2]
        )
        _assert_tiles(self, plan, text)
        # Chapter IDs are distinct and follow the contract formula.
        ids = [c["chapter_id"] for c in plan["chapters"]]
        self.assertEqual(len(set(ids)), 3)
        for chapter in plan["chapters"]:
            self.assertEqual(
                chapter["chapter_id"],
                P.chapter_id_for(
                    revision_id="rev_sanguozhi_001",
                    source_sha256=_locator(text, "rev_sanguozhi_001")[
                        "source_sha256"
                    ],
                    start=chapter["start"],
                    end=chapter["end"],
                ),
            )

    def test_each_chapter_covers_its_prepared_source(self) -> None:
        text = _read("sanguozhi-three-chapters.md")
        manifest = json.loads(
            (FIRST_ROUND / "ingest-manifest.json").read_text(encoding="utf-8")
        )
        upload = next(
            u
            for u in manifest["uploads"]
            if u["ingest_file"] == "ingest/sanguozhi-three-chapters.md"
        )
        plan = P.plan_chapters(
            text, _locator(text, "rev_sanguozhi_001"), "sanguozhi-three-chapters.md"
        )
        self.assertEqual(len(upload["chapters"]), len(plan["chapters"]))
        for record, chapter in zip(upload["chapters"], plan["chapters"]):
            source_text = (SOURCES / Path(record["source_file"]).name).read_bytes()
            source_text = source_text.decode("utf-8")
            body = source_text.rstrip("\n")
            ingest_start, ingest_end = record["ingest_range"]
            # The frozen body sits verbatim inside its planned chapter.
            self.assertEqual(text[ingest_start:ingest_end], body)
            self.assertLessEqual(chapter["start"], ingest_start)
            self.assertGreaterEqual(chapter["end"], ingest_end)
            self.assertIn(body[:30], text[chapter["start"]:chapter["end"]])

    def test_zizhi_single_md_chapter(self) -> None:
        text = _read("zizhi-tongjian-065.md")
        plan = P.plan_chapters(
            text, _locator(text, "rev_zztj_001"), "zizhi-tongjian-065.md"
        )
        self.assertEqual(plan["chapter_count"], 1)
        chapter = plan["chapters"][0]
        self.assertEqual(chapter["title"], "卷第六十五 漢紀五十七（建安十一年至十三年）")
        self.assertEqual((chapter["start"], chapter["end"]), (0, len(text)))
        _assert_tiles(self, plan, text)


class RangeReconstructionTests(unittest.TestCase):
    def test_preface_blank_nested_headings(self) -> None:
        text = (
            "# 史書\n"
            "\n"
            "此卷凡例：紀傳並載。\n"
            "校勘記第一條。\n"
            "\n"
            "\n"
            "## 卷一·本紀\n"
            "\n"
            "太祖武皇帝，沛國譙人也。\n"
            "### 小註一\n"
            "裴松之按：此註當存。\n"
            "\n"
            "建安元年春正月。\n"
            "## 卷二·列傳\n"
            "諸葛亮字孔明。\n"
            "### 小註二\n"
            "出師二表並載於此，不另立章。\n"
        )
        plan = P.plan_chapters(text, _locator(text), "synthetic.md")
        self.assertEqual(plan["chapter_count"], 3)
        preface, first, second = plan["chapters"]
        self.assertEqual(preface["title"], "前言")
        self.assertEqual(first["title"], "卷一·本紀")
        self.assertEqual(second["title"], "卷二·列傳")
        _assert_tiles(self, plan, text)
        # Book line is a registered heading block of the preface;
        # blank runs are separator blocks, never dropped bytes.
        self.assertEqual(preface["blocks"][0]["kind"], "heading")
        self.assertEqual(
            text[preface["blocks"][0]["start"]:preface["blocks"][0]["end"]],
            "# 史書\n",
        )
        self.assertTrue(
            any(b["kind"] == "separator" for b in preface["blocks"])
        )
        # Nested sub-headings belong to their chapter as heading blocks.
        first_kinds = [b["kind"] for b in first["blocks"]]
        self.assertIn("heading", first_kinds)
        sub = next(
            b
            for b in first["blocks"]
            if text[b["start"]:b["end"]].startswith("### 小註一")
        )
        self.assertEqual(sub["kind"], "heading")
        self.assertIn(sub["block_id"], [
            b["block_id"] for b in first["blocks"]
        ])
        self.assertNotIn(sub["block_id"], first["required_block_ids"])
        # Letter-style prose inside a chapter never opens a new chapter.
        self.assertIn("出師二表並載於此，不另立章。", text[second["start"]:second["end"]])

    def test_book_only_prefix_without_preface(self) -> None:
        text = "# 三國志\n\n## 蜀書·先主傳\n\n先主姓劉，諱備。\n"
        plan = P.plan_chapters(text, _locator(text), "book.md")
        self.assertEqual(plan["chapter_count"], 1)
        chapter = plan["chapters"][0]
        self.assertEqual(chapter["title"], "蜀書·先主傳")
        self.assertEqual(chapter["start"], 0)
        self.assertEqual(chapter["blocks"][0]["kind"], "heading")
        _assert_tiles(self, plan, text)

    def test_md_without_chapters_is_single_chapter(self) -> None:
        text = "只有正文，沒有二級標題。\n第二段。\n"
        plan = P.plan_chapters(text, _locator(text), "plain.md")
        self.assertEqual(plan["chapter_count"], 1)
        self.assertEqual(plan["chapters"][0]["title"], "plain")
        _assert_tiles(self, plan, text)

    def test_md_without_chapters_uses_book_title(self) -> None:
        text = "# 資治通鑑\n\n卷首總敘。\n"
        plan = P.plan_chapters(text, _locator(text), "book.md")
        self.assertEqual(plan["chapters"][0]["title"], "資治通鑑")


class EncodingCoordinateTests(unittest.TestCase):
    def test_bom_crlf_extended_cjk_code_points(self) -> None:
        # 𠀋 (U+2000B) is one code point but a surrogate pair in UTF-16;
        # offsets must be code points of the normalized text.
        raw = (
            b"\xef\xbb\xbf"
            b"## \xe5\x8d\xb7\xe4\xb8\x80\r\n"
            b"\r\n"
            b"\xe5\x85\x88\xe4\xb8\xbb\xe5\xa7\x93\xe5\x8a\x89\xf0\xa0\x80\x8b\xe8\xa8\x98\r\n"
        )
        normalized, source_sha, normalized_sha = C.normalize_source_bytes(raw)
        self.assertFalse(normalized.startswith("𠀋") or normalized.startswith("\ufeff"))
        self.assertNotIn("\r", normalized)
        locator = {
            "revision_id": "rev_bom_001",
            "source_sha256": source_sha,
            "normalized_sha256": normalized_sha,
        }
        plan = P.plan_chapters(normalized, locator, "bom.md")
        self.assertEqual(plan["chapter_count"], 1)
        chapter = plan["chapters"][0]
        self.assertEqual((chapter["start"], chapter["end"]), (0, len(normalized)))
        _assert_tiles(self, plan, normalized)
        body_text = "先主姓劉𠀋記\n"
        self.assertIn(body_text, normalized)
        body_block = next(
            b
            for b in chapter["blocks"]
            if normalized[b["start"]:b["end"]] == body_text
        )
        self.assertEqual(body_block["kind"], "body")
        # One extended CJK char counts as one coordinate step.
        self.assertEqual(
            body_block["end"] - body_block["start"], len(body_text)
        )

    def test_normalized_drift_fails_closed(self) -> None:
        text = "## 卷一\n\n正文。\n"
        locator = _locator(text + "extra")
        with self.assertRaises(PersistenceError) as ctx:
            P.plan_chapters(text, locator, "drift.md")
        self.assertIn(P.CODE_HASH_DRIFT, str(ctx.exception))


class DeterminismTests(unittest.TestCase):
    def test_same_input_same_plan_and_hash(self) -> None:
        text = _read("sanguozhi-three-chapters.md")
        locator = _locator(text, "rev_det_001")
        first = P.plan_chapters(text, locator, "sanguozhi-three-chapters.md")
        second = P.plan_chapters(text, locator, "sanguozhi-three-chapters.md")
        self.assertEqual(first, second)
        # plan_sha256 is the canonical hash of the versioned plan payload.
        recomputed = hashlib.sha256(
            canonical_json_bytes(
                {
                    "version": C.PLAN_VERSION,
                    "revision_id": locator["revision_id"],
                    "source_sha256": locator["source_sha256"],
                    "normalized_sha256": locator["normalized_sha256"],
                    "chapters": first["chapters"],
                }
            )
        ).hexdigest()
        self.assertEqual(first["plan_sha256"], recomputed)

    def test_txt_md_same_body_differ_in_structure_only(self) -> None:
        body = "先主姓劉，諱備。\n"
        txt_plan = P.plan_chapters(body, _locator(body), "a.txt")
        md_plan = P.plan_chapters(body, _locator(body), "a.md")
        self.assertEqual(txt_plan["chapters"][0]["required_block_ids"],
                         md_plan["chapters"][0]["required_block_ids"])
        # Filenames select the entry; the same body keeps the same blocks.
        self.assertEqual(txt_plan["chapters"][0]["blocks"],
                         md_plan["chapters"][0]["blocks"])


class CapacityTests(unittest.TestCase):
    def test_over_limit_whole_chapter_unsupported_source_intact(self) -> None:
        text = "甲" * 40000 + "\n"
        snapshot = text
        with self.assertRaises(PersistenceError) as ctx:
            P.plan_chapters(text, _locator(text), "long.txt")
        self.assertIn(P.CODE_OVER_LIMIT, str(ctx.exception))
        self.assertIn("32768", str(ctx.exception))
        self.assertEqual(text, snapshot)

    def test_rejected_sample_is_not_truncated_into_success(self) -> None:
        raw = (REJECTED / "over-limit-sample.md").read_bytes()
        text = raw.decode("utf-8")
        self.assertGreater(len(text), 32768)
        with self.assertRaises(PersistenceError) as ctx:
            P.plan_chapters(text, _locator(text), "over-limit-sample.md")
        self.assertIn(P.CODE_OVER_LIMIT, str(ctx.exception))
        # The source is left intact for the caller: no truncation happened.
        self.assertEqual(text, raw.decode("utf-8"))

    def test_small_limit_rejects_without_resplitting(self) -> None:
        text = "## 甲\n\n正文一段。\n\n## 乙\n\n正文二段。\n"
        tiny = C.ChapterLimits(
            max_source_chars=8,
            max_prompt_chars=262144,
            max_response_chars=524288,
            max_response_bytes=4 * 1024 * 1024,
            max_output_tokens=65536,
        )
        with self.assertRaises(PersistenceError) as ctx:
            P.plan_chapters(text, _locator(text), "two.md", limits=tiny)
        self.assertIn(P.CODE_OVER_LIMIT, str(ctx.exception))
        # The budget gate never re-splits a chapter into smaller chunks:
        # the failure names the whole chapter, not a sub-range.
        self.assertIn("chapter 0", str(ctx.exception))


class StructureRejectionTests(unittest.TestCase):
    def test_conflicting_book_titles_rejected(self) -> None:
        text = "# 甲書\n\n## 卷一\n\n正文一。\n\n# 乙書\n\n## 卷二\n\n正文二。\n"
        with self.assertRaises(PersistenceError) as ctx:
            P.plan_chapters(text, _locator(text), "conflict.md")
        self.assertIn(P.CODE_STRUCTURE_AMBIGUOUS, str(ctx.exception))

    def test_repeated_identical_book_title_tolerated(self) -> None:
        text = "# 甲書\n\n## 卷一\n\n正文一。\n\n# 甲書\n\n尾聲。\n"
        plan = P.plan_chapters(text, _locator(text), "repeat.md")
        self.assertEqual(plan["chapter_count"], 1)
        _assert_tiles(self, plan, text)

    def test_duplicate_chapter_titles_rejected(self) -> None:
        text = "## 卷一\n\n正文一。\n\n## 卷一\n\n正文二。\n"
        with self.assertRaises(PersistenceError) as ctx:
            P.plan_chapters(text, _locator(text), "dup.md")
        self.assertIn(P.CODE_DUPLICATE_CHAPTER, str(ctx.exception))

    def test_bodyless_chapter_rejected(self) -> None:
        text = "## 空章\n\n## 實章\n\n正文。\n"
        with self.assertRaises(PersistenceError) as ctx:
            P.plan_chapters(text, _locator(text), "empty.md")
        self.assertIn(P.CODE_BODYLESS_CHAPTER, str(ctx.exception))


class InputValidationTests(unittest.TestCase):
    def test_empty_text_rejected(self) -> None:
        with self.assertRaises(PersistenceError) as ctx:
            P.plan_chapters("", _locator("x"), "a.txt")
        self.assertIn(P.CODE_EMPTY_TEXT, str(ctx.exception))

    def test_non_string_text_rejected(self) -> None:
        with self.assertRaises(PersistenceError):
            P.plan_chapters(b"bytes", _locator("x"), "a.txt")

    def test_bad_locator_rejected(self) -> None:
        text = "正文。\n"
        for bad in (
            None,
            "rev_001",
            {},
            {"revision_id": "", "source_sha256": "x", "normalized_sha256": "y"},
            {
                "revision_id": "r",
                "source_sha256": "not-hex",
                "normalized_sha256": "0" * 64,
            },
        ):
            with self.assertRaises(PersistenceError, msg=repr(bad)) as ctx:
                P.plan_chapters(text, bad, "a.txt")
            self.assertIn(P.CODE_BAD_LOCATOR, str(ctx.exception))

    def test_unsupported_format_rejected(self) -> None:
        text = "正文。\n"
        for name in ("a.pdf", "a", "a.markdown", ""):
            with self.assertRaises(PersistenceError, msg=repr(name)) as ctx:
                P.plan_chapters(text, _locator(text), name)
            self.assertIn(P.CODE_UNSUPPORTED_FORMAT, str(ctx.exception))

    def test_uppercase_suffix_accepted(self) -> None:
        text = "正文。\n"
        plan = P.plan_chapters(text, _locator(text), "A.TXT")
        self.assertEqual(plan["chapter_count"], 1)
        plan_md = P.plan_chapters("## 卷一\n\n正文。\n", _locator("## 卷一\n\n正文。\n"), "B.MD")
        self.assertEqual(plan_md["chapter_count"], 1)

    def test_document_id_carried_when_present(self) -> None:
        text = "正文。\n"
        locator = dict(_locator(text), document_id="doc_001")
        plan = P.plan_chapters(text, locator, "a.txt")
        self.assertEqual(plan["document_id"], "doc_001")
        self.assertEqual(plan["chapters"][0]["document_id"], "doc_001")


class RequestBuilderTests(unittest.TestCase):
    def test_request_feeds_t01_validator(self) -> None:
        text = "## 卷一\n\n建安十三年，曹操屯江陵。\n\n周瑜敗操於赤壁。\n"
        locator = _locator(text, "rev_req_001")
        plan = P.plan_chapters(text, locator, "req.md")
        request = P.build_chapter_request(plan, 0, text)
        self.assertEqual(request["normalized_text"], text[0:len(text)])
        self.assertEqual(request["blocks"][0]["start"], 0)
        self.assertEqual(
            request["blocks"][-1]["end"], len(request["normalized_text"])
        )
        self.assertEqual(request["plan_version"], C.PLAN_VERSION)
        report = C.validate_chapter_candidate(request, {})
        request_errors = [
            message
            for message in report["errors"]["identity_binding"]
            if message.startswith("request:")
        ]
        self.assertEqual(request_errors, [])

    def test_request_slices_and_rebases_absolute_coordinates(self) -> None:
        text = _read("sanguozhi-three-chapters.md")
        locator = _locator(text, "rev_req_002")
        plan = P.plan_chapters(text, locator, "sanguozhi-three-chapters.md")
        for index, chapter in enumerate(plan["chapters"]):
            request = P.build_chapter_request(plan, index, text)
            self.assertEqual(
                request["normalized_text"],
                text[chapter["start"]:chapter["end"]],
            )
            for block, planned in zip(request["blocks"], chapter["blocks"]):
                self.assertEqual(block["block_id"], planned["block_id"])
                self.assertEqual(block["start"], planned["start"] - chapter["start"])
                self.assertEqual(block["end"], planned["end"] - chapter["start"])

    def test_request_rejects_wrong_bytes(self) -> None:
        text = "## 卷一\n\n正文。\n"
        plan = P.plan_chapters(text, _locator(text), "req.md")
        with self.assertRaises(PersistenceError) as ctx:
            P.build_chapter_request(plan, 0, text + "drift")
        self.assertIn(P.CODE_HASH_DRIFT, str(ctx.exception))
        with self.assertRaises(PersistenceError):
            P.build_chapter_request(plan, 5, text)
        with self.assertRaises(PersistenceError):
            P.build_chapter_request({}, 0, text)


if __name__ == "__main__":
    unittest.main()
