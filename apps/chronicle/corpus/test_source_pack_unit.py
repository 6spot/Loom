"""Unit contracts for the C1-T13 pinned source-pack operator (no network)."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import source_pack  # noqa: E402


class SectionTextTests(unittest.TestCase):
    def test_exact_heading_extracts_paragraphs_and_stops_at_next_heading(self) -> None:
        html = """
        <h2><span class='mw-editsection'>[编辑]</span>先主 <b>劉備</b></h2>
        <p>第一段。<span class='annotation'>裴注文字。</span><sup class='reference'>[1]</sup></p>
        <p>第二段<br/>續行。</p>
        <h2>諸葛亮</h2>
        <p>不可收入。</p>
        """
        text = source_pack.extract_section_text(html, "先主 劉備")
        self.assertEqual("第一段。裴注文字。\n\n第二段\n續行。\n", text)
        self.assertNotIn("[编辑]", text)
        self.assertNotIn("[1]", text)
        self.assertNotIn("不可收入", text)

    def test_heading_normalization_is_nfkc_and_whitespace_insensitive(self) -> None:
        html = "<h2>諸 葛 亮</h2><p>孔明。</p><h2>關羽</h2>"
        self.assertEqual("孔明。\n", source_pack.extract_section_text(html, "諸葛亮"))

    def test_missing_or_empty_section_fails_closed(self) -> None:
        with self.assertRaisesRegex(source_pack.SourcePackError, "heading not found"):
            source_pack.extract_section_text("<h2>周瑜</h2><p>正文</p>", "魯肅")
        with self.assertRaisesRegex(source_pack.SourcePackError, "no paragraphs"):
            source_pack.extract_section_text("<h2>魯肅</h2><div>不是段落</div><h2>呂蒙</h2>", "魯肅")


class ManifestTests(unittest.TestCase):
    def base_manifest(self) -> dict:
        return {
            "schema": source_pack.PACK_SCHEMA,
            "version": source_pack.PACK_VERSION,
            "pack_id": "unit-pack",
            "language": "zh-Hant",
            "acquisition": {
                "endpoint": "https://example.test/w/api.php",
                "transform_version": "unit-transform-v1",
            },
            "sources": [
                {
                    "key": "a",
                    "title": "A傳",
                    "filename": "a.txt",
                    "page_title": "書/卷1",
                    "oldid": 10,
                    "section": "甲",
                },
                {
                    "key": "b",
                    "title": "B傳",
                    "filename": "b.txt",
                    "page_title": "書/卷1",
                    "oldid": 10,
                    "section": "乙",
                },
            ],
        }

    def write_manifest(self, root: Path, payload: dict) -> Path:
        path = root / "manifest.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_duplicate_key_filename_bad_oldid_and_unsafe_filename_fail(self) -> None:
        mutations = []
        payload = self.base_manifest(); payload["sources"][1]["key"] = "a"; mutations.append(payload)
        payload = self.base_manifest(); payload["sources"][1]["filename"] = "a.txt"; mutations.append(payload)
        payload = self.base_manifest(); payload["sources"][0]["oldid"] = 0; mutations.append(payload)
        payload = self.base_manifest(); payload["sources"][0]["filename"] = "../a.txt"; mutations.append(payload)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index, bad in enumerate(mutations):
                with self.subTest(index=index):
                    with self.assertRaises(source_pack.SourcePackError):
                        source_pack.load_manifest(self.write_manifest(root, bad))

    def test_prepare_fetches_shared_oldid_once_and_is_deterministic(self) -> None:
        manifest = self.base_manifest()
        rendered = "<h2>甲</h2><p>甲正文。</p><h2>乙</h2><p>乙正文。</p><h2>丙</h2>"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out1, out2 = root / "one", root / "two"
            with mock.patch.object(source_pack, "_fetch_parse_html", return_value=rendered) as fetch:
                first = source_pack.prepare_pack(manifest, out1)
            fetch.assert_called_once_with("https://example.test/w/api.php", 10, timeout=45.0)
            with mock.patch.object(source_pack, "_fetch_parse_html", return_value=rendered):
                second = source_pack.prepare_pack(manifest, out2)

            self.assertEqual(first, second)
            self.assertEqual(b"\xe7\x94\xb2\xe6\xad\xa3\xe6\x96\x87\xe3\x80\x82\n", (out1 / "a.txt").read_bytes())
            self.assertEqual(b"\xe4\xb9\x99\xe6\xad\xa3\xe6\x96\x87\xe3\x80\x82\n", (out1 / "b.txt").read_bytes())
            for item in first["sources"]:
                raw = (out1 / item["filename"]).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), item["sha256"])
                self.assertEqual(len(raw), item["bytes"])
                self.assertIn("oldid=10", item["source_label"])
                self.assertIn("transform=unit-transform-v1", item["source_label"])


class FakeStudioClient:
    def __init__(self) -> None:
        self.documents: dict[str, dict] = {}
        self.revisions: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}
        self.calls: list[tuple] = []

    def get_or_create_document(self, title: str):
        self.calls.append(("document", title))
        if title in self.documents:
            return self.documents[title], False
        doc = {"document_id": f"doc-{len(self.documents) + 1}", "title": title}
        self.documents[title] = doc
        return doc, True

    def upload_revision(self, document_id: str, source: dict, raw: bytes):
        sha = hashlib.sha256(raw).hexdigest()
        self.calls.append(("revision", document_id, source["filename"], sha))
        if sha in self.revisions:
            result = dict(self.revisions[sha]); result["duplicate"] = True; return result
        revision = {
            "revision_id": f"rev-{len(self.revisions) + 1}",
            "revision_no": 1,
            "source_sha256": sha,
            "duplicate": False,
        }
        self.revisions[sha] = revision
        return dict(revision)

    def get_or_create_job(self, revision_id: str):
        self.calls.append(("job", revision_id))
        if revision_id in self.jobs:
            return self.jobs[revision_id], False
        job = {"job_id": f"job-{len(self.jobs) + 1}", "status": "queued"}
        self.jobs[revision_id] = job
        return job, True


class IngestTests(unittest.TestCase):
    def write_prepared(self, root: Path, text: str = "史料正文。\n") -> dict:
        raw = text.encode("utf-8")
        source = {
            "key": "unit",
            "title": "單元傳",
            "filename": "unit.txt",
            "language": "zh-Hant",
            "source_label": "pinned unit source",
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        (root / "unit.txt").write_bytes(raw)
        payload = {
            "schema": source_pack.PREPARED_SCHEMA,
            "version": source_pack.PREPARED_VERSION,
            "pack_id": "unit-pack",
            "manifest_sha256": "0" * 64,
            "sources": [source],
        }
        (root / "prepared.json").write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def test_ingest_uses_studio_documents_revisions_jobs_and_is_retry_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_prepared(root)
            client = FakeStudioClient()
            first = source_pack.ingest_prepared(root, client)
            second = source_pack.ingest_prepared(root, client)

        self.assertEqual("chronicle.corpus-ingestion-report", first["schema"])
        self.assertTrue(first["sources"][0]["document_created"])
        self.assertTrue(first["sources"][0]["job_created"])
        self.assertFalse(second["sources"][0]["document_created"])
        self.assertTrue(second["sources"][0]["revision_duplicate"])
        self.assertFalse(second["sources"][0]["job_created"])
        self.assertEqual(first["sources"][0]["revision_id"], second["sources"][0]["revision_id"])
        self.assertEqual(first["sources"][0]["job_id"], second["sources"][0]["job_id"])

    def test_tampered_prepared_bytes_fail_before_any_studio_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_prepared(root)
            (root / "unit.txt").write_text("被篡改。\n", encoding="utf-8")
            client = FakeStudioClient()
            with self.assertRaisesRegex(source_pack.SourcePackError, "drift"):
                source_pack.ingest_prepared(root, client)
            self.assertEqual([], client.calls)


if __name__ == "__main__":
    unittest.main()
