"""C2-R1-T02 first-round acceptance corpus contracts (offline, no network).

Verifies the frozen two-work / four-chapter corpus under
``apps/chronicle/corpus/first-round``:

* fixed chapters, works and pinned revisions (no open selections);
* re-prepare reproducibility (manifest hash + file hashes) and reuse of the
  exact c1-t13 bytes for the three Sanguozhi chapters;
* deterministic ingest derivation with exact per-chapter hash/range back to
  the download files, and proof that the three Sanguozhi chapters share one
  revision (one upload file) rather than three separate jobs;
* 12+ real locating checkpoints plus a clearly separated synthetic negative;
* capacity gate: every real chapter within 32768 chars, an explicit
  rejection sample above the cap, and intact head/tail/commentary bytes.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
FIRST_ROUND = HERE / "first-round"
SOURCES = FIRST_ROUND / "sources"
INGEST = FIRST_ROUND / "ingest"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import source_pack  # noqa: E402
import importlib.util  # noqa: E402

CHAPTER_LIMIT = 32768

EXPECTED_SOURCES = {
    "xianzhu-liubei": {
        "filename": "sanguozhi-032-xianzhu-liubei.txt",
        "page_title": "三國志/卷32",
        "oldid": 2583378,
        "bytes": 37474,
        "sha256": "ea40a7087560fe9e693e6f81cb7d1689704f888a40b5b8a8bf7169ec272994e8",
    },
    "zhou-yu": {
        "filename": "sanguozhi-054-zhou-yu.txt",
        "page_title": "三國志/卷54",
        "oldid": 2387393,
        "bytes": 14996,
        "sha256": "63db082c4e763be3b56c87cb56e2bed904af5325e9a498b07d932d3b5af1f43e",
    },
    "lu-su": {
        "filename": "sanguozhi-054-lu-su.txt",
        "page_title": "三國志/卷54",
        "oldid": 2387393,
        "bytes": 10715,
        "sha256": "1550e1735f44eda7adb9bf27f4ed2cbc9c2185baf6634400140cd52ac312553d",
    },
    "zztj-065": {
        "filename": "zizhi-tongjian-065-quan.txt",
        "page_title": "資治通鑑/卷065",
        "oldid": 2306420,
        "bytes": 31786,
        "sha256": "c7f80c6baff73a0caa0bbf365117b9ae91892da590ab3830392deb9bcb46fd38",
    },
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_build_ingest():
    spec = importlib.util.spec_from_file_location(
        "first_round_build_ingest", FIRST_ROUND / "build_ingest.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ManifestTests(unittest.TestCase):
    def test_four_chapters_two_works_frozen(self) -> None:
        manifest = _load_json(FIRST_ROUND / "source-pack.json")
        self.assertEqual(manifest["schema"], source_pack.PACK_SCHEMA)
        self.assertEqual(manifest["pack_id"], "c2-r1-t02-first-round-v1")
        keys = [item["key"] for item in manifest["sources"]]
        self.assertEqual(keys, ["xianzhu-liubei", "zhou-yu", "lu-su", "zztj-065"])
        works = manifest["works"]
        self.assertEqual(len(works), 2)
        self.assertEqual(works[0]["work"], "三國志")
        self.assertEqual(works[0]["chapters"], ["xianzhu-liubei", "zhou-yu", "lu-su"])
        self.assertEqual(works[1]["work"], "資治通鑑")
        self.assertEqual(works[1]["chapters"], ["zztj-065"])
        for item in manifest["sources"]:
            expected = EXPECTED_SOURCES[item["key"]]
            self.assertEqual(item["filename"], expected["filename"])
            self.assertEqual(item["page_title"], expected["page_title"])
            self.assertEqual(item["oldid"], expected["oldid"])

    def test_prepared_reproduces_manifest_and_file_hashes(self) -> None:
        manifest = _load_json(FIRST_ROUND / "source-pack.json")
        prepared = _load_json(SOURCES / "prepared.json")
        self.assertEqual(prepared["schema"], source_pack.PREPARED_SCHEMA)
        self.assertEqual(prepared["pack_id"], manifest["pack_id"])
        canonical = json.dumps(
            manifest, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), prepared["manifest_sha256"])
        self.assertEqual(len(prepared["sources"]), 4)
        for record in prepared["sources"]:
            expected = EXPECTED_SOURCES[record["key"]]
            raw = (SOURCES / record["filename"]).read_bytes()
            self.assertEqual(len(raw), expected["bytes"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected["sha256"])
            self.assertEqual(record["bytes"], expected["bytes"])
            self.assertEqual(record["sha256"], expected["sha256"])

    def test_sanguozhi_reuses_exact_c1_t13_bytes(self) -> None:
        legacy = _load_json(HERE / "c1-t13" / "sources" / "prepared.json")
        legacy_by_key = {item["key"]: item for item in legacy["sources"]}
        prepared = _load_json(SOURCES / "prepared.json")
        for key in ("xianzhu-liubei", "zhou-yu", "lu-su"):
            record = next(item for item in prepared["sources"] if item["key"] == key)
            self.assertEqual(record["sha256"], legacy_by_key[key]["sha256"])
            self.assertEqual(record["bytes"], legacy_by_key[key]["bytes"])
            fresh = (SOURCES / record["filename"]).read_bytes()
            old = (HERE / "c1-t13" / "sources" / legacy_by_key[key]["filename"]).read_bytes()
            self.assertEqual(fresh, old)

    def test_full_page_transform_is_deterministic_without_network(self) -> None:
        html = (
            "<h2>甲</h2><p>甲正文。</p>"
            "<h2>乙</h2><p>乙正文。</p>"
            "<div class=\"licenseContainer\"><p>站點授權，不屬正文。</p></div>"
        )
        probe = {
            "schema": source_pack.PACK_SCHEMA,
            "version": source_pack.PACK_VERSION,
            "pack_id": "probe",
            "language": "zh-Hant",
            "acquisition": {"endpoint": "https://example.test/w/api.php", "transform_version": "probe-v1"},
            "sources": [
                {
                    "key": "sec",
                    "title": "甲傳",
                    "filename": "sec.txt",
                    "page_title": "書/卷1",
                    "oldid": 7,
                    "extract": "section",
                    "section": "甲",
                },
                {
                    "key": "full",
                    "title": "全卷",
                    "filename": "full.txt",
                    "page_title": "書/卷1",
                    "oldid": 7,
                    "extract": "full_page",
                },
            ],
        }
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "probe-manifest.json"
            manifest_path.write_text(
                json.dumps(probe, ensure_ascii=False), encoding="utf-8"
            )
            validated = source_pack.load_manifest(manifest_path)
            with mock.patch.object(
                source_pack, "_fetch_parse_html", return_value=html
            ) as fetch:
                first = source_pack.prepare_pack(validated, Path(tmp) / "one")
                fetch.assert_called_once_with(
                    "https://example.test/w/api.php", 7, timeout=45.0
                )
            with mock.patch.object(
                source_pack, "_fetch_parse_html", return_value=html
            ):
                second = source_pack.prepare_pack(validated, Path(tmp) / "two")
            self.assertEqual(first, second)
            by_key = {item["key"]: item for item in first["sources"]}
            one_full = (Path(tmp) / "one" / "full.txt").read_text(encoding="utf-8")
            self.assertNotIn("站點授權", one_full)
            self.assertIn("甲正文", one_full)
            self.assertEqual(
                (Path(tmp) / "one" / "sec.txt").read_text(encoding="utf-8"), "甲正文。\n"
            )
            self.assertEqual(by_key["sec"]["extract"], "section")
            self.assertEqual(by_key["full"]["extract"], "full_page")
        # The real first-round manifest itself must validate under the same rules.
        source_pack.load_manifest(FIRST_ROUND / "source-pack.json")


class IngestTests(unittest.TestCase):
    def test_ingest_derivation_is_deterministic(self) -> None:
        builder = _load_build_ingest()
        sanguozhi_text, sanguozhi_records = builder.build_markdown(
            builder.BOOK_SANGUOZHI, builder.CHAPTERS_SANGUOZHI
        )
        zztj_text, zztj_records = builder.build_markdown(
            builder.BOOK_ZZTJ, builder.CHAPTERS_ZZTJ
        )
        self.assertEqual(
            sanguozhi_text,
            (INGEST / "sanguozhi-three-chapters.md").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            zztj_text, (INGEST / "zizhi-tongjian-065.md").read_text(encoding="utf-8")
        )
        stored = _load_json(FIRST_ROUND / "ingest-manifest.json")
        self.assertEqual(len(stored["uploads"]), 2)
        self.assertEqual(len(sanguozhi_records), 3)
        self.assertEqual(len(zztj_records), 1)

    def test_each_chapter_matches_exact_source_bytes_and_range(self) -> None:
        stored = _load_json(FIRST_ROUND / "ingest-manifest.json")
        for upload in stored["uploads"]:
            ingest_text = (FIRST_ROUND / upload["ingest_file"]).read_text(encoding="utf-8")
            self.assertEqual(
                hashlib.sha256((FIRST_ROUND / upload["ingest_file"]).read_bytes()).hexdigest(),
                upload["sha256"],
            )
            for chapter in upload["chapters"]:
                source_text = (FIRST_ROUND / chapter["source_file"]).read_text(encoding="utf-8")
                body = source_text.rstrip("\n")
                start, end = chapter["ingest_range"]
                self.assertEqual(ingest_text[start:end], body)
                self.assertEqual(body + "\n", source_text)
                self.assertEqual(chapter["source_range"], [0, len(body)])
                self.assertEqual(
                    chapter["source_sha256"],
                    hashlib.sha256(
                        (FIRST_ROUND / chapter["source_file"]).read_bytes()
                    ).hexdigest(),
                )

    def test_sanguozhi_chapters_share_one_revision(self) -> None:
        stored = _load_json(FIRST_ROUND / "ingest-manifest.json")
        sanguozhi = next(
            item for item in stored["uploads"] if item["book"] == "三國志"
        )
        ingest_shas = {chapter["ingest_sha256"] for chapter in sanguozhi["chapters"]}
        self.assertEqual(len(ingest_shas), 1)
        self.assertEqual(next(iter(ingest_shas)), sanguozhi["sha256"])
        text = (FIRST_ROUND / sanguozhi["ingest_file"]).read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# 三國志\n"))
        self.assertEqual(text.count("\n## "), 3)

    def test_markdown_chapter_structure_has_no_stray_headings(self) -> None:
        for name, expected_h2 in (
            ("sanguozhi-three-chapters.md", 3),
            ("zizhi-tongjian-065.md", 1),
        ):
            lines = (INGEST / name).read_text(encoding="utf-8").splitlines()
            h1 = [line for line in lines if line.startswith("# ")]
            h2 = [line for line in lines if line.startswith("## ")]
            self.assertEqual(len(h1), 1)
            self.assertEqual(len(h2), expected_h2)
            for line in lines:
                if line.startswith("#"):
                    self.assertTrue(
                        line.startswith("# ") or line.startswith("## "),
                        f"stray heading line in {name}: {line!r}",
                    )


class CasesTests(unittest.TestCase):
    def test_twelve_real_cases_locate_exactly_and_synthetic_is_separate(self) -> None:
        bundle = _load_json(FIRST_ROUND / "cases.json")
        real = [case for case in bundle["cases"] if not case.get("synthetic")]
        synthetic = [case for case in bundle["cases"] if case.get("synthetic")]
        self.assertGreaterEqual(len(real), 12)
        self.assertGreaterEqual(len(synthetic), 1)
        category_kinds = {case["category"] for case in real}
        for required in (
            "same-chapter-appellation",
            "cross-chapter-recurrence",
            "cross-book-same-event",
            "place-ambiguity",
            "annotation-attribution",
            "no-direct-claim",
            "head-completeness",
        ):
            self.assertIn(required, category_kinds)
        for case in real:
            self.assertTrue(case["refs"], case["id"])
            for ref in case["refs"]:
                text = (FIRST_ROUND / ref["file"]).read_text(encoding="utf-8")
                start, end = ref["start"], ref["end"]
                self.assertEqual(text[start:end], ref["quote"], f"{case['id']} {ref}")
                before = text[:start]
                actual_occurrence = before.count(ref["quote"]) + 1
                self.assertEqual(actual_occurrence, ref["occurrence"], f"{case['id']} {ref}")
                self.assertGreaterEqual(start, 0)
                self.assertLessEqual(end, len(text))
        for case in synthetic:
            self.assertEqual(case["refs"], [])
            self.assertTrue(case.get("synthetic"))
        negative = next(case for case in bundle["cases"] if case["id"] == "T02-N01")
        self.assertTrue(negative["synthetic"])
        corpus = "".join(
            (SOURCES / name).read_text(encoding="utf-8")
            for name in (
                "sanguozhi-032-xianzhu-liubei.txt",
                "sanguozhi-054-zhou-yu.txt",
                "sanguozhi-054-lu-su.txt",
                "zizhi-tongjian-065-quan.txt",
            )
        )
        self.assertNotIn("江陵太守劉備", corpus)


class ScaleTests(unittest.TestCase):
    def test_real_chapters_within_limit_and_rejection_sample_fails(self) -> None:
        report = _load_json(FIRST_ROUND / "scale-report.json")
        self.assertEqual(report["chapter_limit_chars"], CHAPTER_LIMIT)
        self.assertFalse(report["substitution"]["needed"])
        for chapter in report["chapters"]:
            self.assertLessEqual(chapter["chars"], CHAPTER_LIMIT, chapter["chapter"])
            self.assertTrue(chapter["within_limit"])
        rejected = report["rejection_sample"]
        self.assertTrue(rejected["synthetic"])
        self.assertEqual(rejected["expected_verdict"], "reject")
        rejected_text = (FIRST_ROUND / rejected["file"]).read_text(encoding="utf-8")
        self.assertGreater(len(rejected_text), CHAPTER_LIMIT)

    def test_head_tail_and_commentary_bytes_intact(self) -> None:
        volume = (SOURCES / "zizhi-tongjian-065-quan.txt").read_text(encoding="utf-8")
        self.assertTrue(volume.startswith("資治通鑑 第065卷\n"))
        self.assertIn("【漢紀五十七】\u3000起柔兆閹茂，盡著雍困敦，凡三年。", volume[:200])
        self.assertTrue(volume.endswith("以齊為太守。\n"))
        self.assertNotIn("公有领域", volume)
        self.assertNotIn("Public domain", volume)
        self.assertIn("習鑿齒論曰", volume)
        xianzhu = (SOURCES / "sanguozhi-032-xianzhu-liubei.txt").read_text(encoding="utf-8")
        self.assertTrue(xianzhu.startswith("先主姓劉，諱備"))
        self.assertTrue(xianzhu.endswith("即是言先主死意。〉\n"))
        self.assertIn("〈《典略》曰", xianzhu)
        zhouyu = (SOURCES / "sanguozhi-054-zhou-yu.txt").read_text(encoding="utf-8")
        self.assertTrue(zhouyu.startswith("周瑜字公瑾"))
        self.assertIn("〈《江表傳》曰", zhouyu)
        lusu = (SOURCES / "sanguozhi-054-lu-su.txt").read_text(encoding="utf-8")
        self.assertTrue(lusu.startswith("魯肅字子敬"))


if __name__ == "__main__":
    unittest.main()
