"""Unit tests for Chronicle C1-T3 document validation and source storage.

Pure filesystem/tmp tests: no PostgreSQL required, so these run anywhere.
Database round trips live in test_documents_postgres.py.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import documents
from common import PersistenceError


class ValidationTests(unittest.TestCase):
    def test_accepts_txt_and_md_only(self) -> None:
        self.assertEqual(documents.media_type_for_filename("wudi.txt"), "text/plain")
        self.assertEqual(documents.media_type_for_filename("notes.MD"), "text/markdown")
        for bad in ("book.pdf", "archive.epub", "doc.docx", "noext", "scan.png"):
            with self.assertRaises(PersistenceError, msg=bad):
                documents.media_type_for_filename(bad)

    def test_filename_must_be_a_plain_basename(self) -> None:
        self.assertEqual(documents.sanitize_filename("wudi-juan1.txt"), "wudi-juan1.txt")
        for bad in (
            "",
            "   ",
            "../evil.txt",
            "sub/dir.txt",
            "back\\slash.txt",
            ".hidden.txt",
            "..",
            ".",
            "a" * 256,
            "nul\x00byte.txt",
            "tab\tname.txt",
            123,
            None,
        ):
            with self.assertRaises(PersistenceError, msg=repr(bad)):
                documents.sanitize_filename(bad)

    def test_strict_utf8_decoding(self) -> None:
        self.assertEqual(documents.decode_source("武帝纪\n".encode("utf-8")), "武帝纪\n")
        # BOM is stripped, CRLF/CR are normalized for deterministic locators.
        self.assertEqual(
            documents.decode_source(b"\xef\xbb\xbfline1\r\nline2\rline3"),
            "line1\nline2\nline3",
        )
        for bad in (b"\xff\xfe invalid", b"\x80 lone", "text".encode("utf-16")):
            with self.assertRaises(PersistenceError, msg=repr(bad)):
                documents.decode_source(bad)
        with self.assertRaises(PersistenceError):
            documents.decode_source("not-bytes")  # type: ignore[arg-type]

    def test_max_upload_bytes_from_env(self) -> None:
        self.assertEqual(documents.max_upload_bytes({}), documents.DEFAULT_MAX_UPLOAD_BYTES)
        self.assertEqual(documents.max_upload_bytes({"CHRONICLE_MAX_UPLOAD_BYTES": " 42 "}), 42)
        for bad in ("0", "-5", "huge", "1.5"):
            with self.assertRaises(PersistenceError, msg=bad):
                documents.max_upload_bytes({"CHRONICLE_MAX_UPLOAD_BYTES": bad})

    def test_storage_dir_from_env(self) -> None:
        default = documents.storage_dir_from_env({})
        self.assertEqual(default, Path.cwd() / "chronicle-sources")
        custom = documents.storage_dir_from_env({"CHRONICLE_SOURCE_DIR": "/data/chronicle/src"})
        self.assertEqual(custom, Path("/data/chronicle/src"))


class StorageKeyTests(unittest.TestCase):
    def test_keys_are_relative_and_unique_per_revision(self) -> None:
        doc = uuid.uuid4()
        key_txt = documents.storage_key_for(doc, uuid.uuid4(), "wudi.txt")
        key_md = documents.storage_key_for(doc, uuid.uuid4(), "notes.md")
        self.assertTrue(key_txt.startswith(f"documents/{doc}/"))
        self.assertTrue(key_txt.endswith(".txt"))
        self.assertTrue(key_md.endswith(".md"))
        self.assertNotEqual(
            documents.storage_key_for(doc, uuid.uuid4(), "wudi.txt"),
            documents.storage_key_for(doc, uuid.uuid4(), "wudi.txt"),
        )

    def test_resolve_refuses_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            resolved = documents.resolve_storage_path(base, "documents/a/b.txt")
            self.assertEqual(resolved.parent.parent.name, "documents")
            for bad in ("/absolute/key.txt", "documents/../evil.txt", "a\\b.txt", ""):
                with self.assertRaises(PersistenceError, msg=bad):
                    documents.resolve_storage_path(base, bad)


class AtomicWriteTests(unittest.TestCase):
    def test_write_is_atomic_and_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            dest = documents.write_source_file(base, "documents/d/r.txt", "武帝纪".encode())
            self.assertTrue(dest.is_file())
            self.assertEqual(dest.read_bytes(), "武帝纪".encode("utf-8"))
            self.assertEqual(
                documents.read_revision_bytes(base, "documents/d/r.txt"),
                "武帝纪".encode("utf-8"),
            )
            self.assertEqual(documents.storage_status(base, "documents/d/r.txt"), "present")
            self.assertEqual(documents.storage_status(base, "documents/d/gone.txt"), "missing")

    def test_no_tmp_files_left_behind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            documents.write_source_file(base, "documents/d/r.txt", b"data")
            leftovers = list((base / "documents" / "d").glob(".tmp-*"))
            self.assertEqual(leftovers, [])
            self.assertFalse(os.environ.get("CHRONICLE_SHOULD_NOT_EXIST", ""))

    def test_missing_file_read_fails_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PersistenceError):
                documents.read_revision_bytes(Path(tmp), "documents/d/gone.txt")


class LocatorTests(unittest.TestCase):
    def test_locator_pins_exact_source_span(self) -> None:
        revision = {
            "document_id": str(uuid.uuid4()),
            "revision_id": str(uuid.uuid4()),
            "revision_no": 2,
            "source_sha256": "a" * 64,
            "source_bytes": 1024,
            "content_chars": 512,
            "storage_key": "documents/d/r.txt",
        }
        locator = documents.source_locator(revision)
        self.assertEqual(locator["source_start"], 0)
        self.assertEqual(locator["source_end"], 1024)
        self.assertEqual(locator["source_sha256"], "a" * 64)
        self.assertEqual(locator["revision_no"], 2)


if __name__ == "__main__":
    unittest.main()
