"""PostgreSQL 18 integration tests for Chronicle C1-T3 document uploads.

Covers the full acceptance surface that needs a database: authenticated
flow primitives (create document + upload), deterministic hash/metadata/
storage-key round trips, immutable replacement (new revision preserves the
old one), safe failures (bad encoding, oversize, unsafe names, unknown
documents, interrupted writes), idempotent duplicates, queryable
history/active status, and source locators for later chunk provenance.

Each test gets an isolated database plus an isolated source-data
directory, so filesystem and SQL state never leak between tests.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import control_plane
import documents
from common import PersistenceError
from migrations import apply_migrations


DEFAULT_CONTROL_URL = "postgresql://loom:loom@127.0.0.1:15432/loom_control"


def _control_url() -> str:
    explicit = os.environ.get("LOOM_TEST_POSTGRES_URL")
    url = explicit or DEFAULT_CONTROL_URL
    try:
        with psycopg.connect(url, connect_timeout=2):
            return url
    except psycopg.Error:
        if explicit:
            raise
    subprocess.run(
        ["bash", "tools/postgres-test.sh", "up"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    with psycopg.connect(url, connect_timeout=10):
        return url


def _database_conninfo(control_url: str, database_name: str) -> str:
    params = conninfo_to_dict(control_url)
    params["dbname"] = database_name
    return make_conninfo(**params)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class DocumentUploadPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_c1t3_test_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        self._tmp = tempfile.TemporaryDirectory(prefix="chronicle-c1t3-")
        self.storage_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name))
            )

    def _connect_ready(self):
        conn = psycopg.connect(self.database_url)
        apply_migrations(conn)
        return conn

    def _document(self, conn, title="武帝紀") -> uuid.UUID:
        return control_plane.create_document(conn, title=title)

    def test_upload_round_trip_is_deterministic_and_auditable(self) -> None:
        """Hash/metadata/storage-key round trip for a valid text revision."""
        body = "武帝紀第一\n漢武帝也。\n".encode("utf-8")
        with self._connect_ready() as conn:
            document_id = self._document(conn)
            first = documents.upload_revision(
                conn,
                storage_dir=self.storage_dir,
                document_id=document_id,
                filename="wudi.txt",
                data=body,
                language="zh-CN",
                source_label="二十四史",
            )
            self.assertFalse(first["duplicate"])
            self.assertEqual(first["revision_no"], 1)
            self.assertEqual(first["status"], "active")
            self.assertEqual(first["source_sha256"], _sha(body))
            self.assertEqual(first["source_bytes"], len(body))
            self.assertEqual(first["content_chars"], len(body.decode("utf-8")))
            self.assertEqual(first["source_media_type"], "text/plain")
            self.assertEqual(first["language"], "zh-CN")
            self.assertTrue(first["storage_key"].startswith(f"documents/{document_id}/"))
            self.assertTrue(first["storage_key"].endswith(".txt"))
            self.assertEqual(first["storage_status"], "present")
            self.assertIsNone(first["supersedes_revision_id"])

            # Stored bytes are the exact uploaded bytes; the file lives
            # under the Chronicle-owned data directory via a relative key.
            stored = documents.read_revision_bytes(self.storage_dir, first["storage_key"])
            self.assertEqual(stored, body)
            self.assertFalse(first["storage_key"].startswith("/"))

            # Re-reading through the history API returns identical metadata.
            history = documents.revision_history(
                conn, document_id=document_id, storage_dir=self.storage_dir
            )
            self.assertEqual(len(history), 1)
            for field in (
                "revision_id",
                "source_sha256",
                "source_bytes",
                "content_chars",
                "storage_key",
                "filename",
            ):
                self.assertEqual(history[0][field], first[field])

    def test_markdown_upload_uses_markdown_media_type(self) -> None:
        body = "# 武帝紀\n\n漢武帝也。\n".encode("utf-8")
        with self._connect_ready() as conn:
            document_id = self._document(conn)
            result = documents.upload_revision(
                conn,
                storage_dir=self.storage_dir,
                document_id=document_id,
                filename="wudi.md",
                data=body,
            )
            self.assertEqual(result["source_media_type"], "text/markdown")
            self.assertTrue(result["storage_key"].endswith(".md"))
            self.assertEqual(
                documents.read_revision_bytes(self.storage_dir, result["storage_key"]), body
            )

    def test_replacement_creates_new_revision_and_preserves_old(self) -> None:
        """Replacement is append-only: the old revision row and file stay."""
        first_body = "版本一\n".encode("utf-8")
        second_body = "版本一\n版本二\n".encode("utf-8")
        with self._connect_ready() as conn:
            document_id = self._document(conn)
            first = documents.upload_revision(
                conn,
                storage_dir=self.storage_dir,
                document_id=document_id,
                filename="wudi.txt",
                data=first_body,
            )
            second = documents.upload_revision(
                conn,
                storage_dir=self.storage_dir,
                document_id=document_id,
                filename="wudi.txt",
                data=second_body,
            )
            self.assertEqual(second["revision_no"], 2)
            self.assertEqual(second["supersedes_revision_id"], first["revision_id"])
            self.assertNotEqual(second["revision_id"], first["revision_id"])
            self.assertNotEqual(second["storage_key"], first["storage_key"])
            self.assertFalse(second["duplicate"])

            history = documents.revision_history(
                conn, document_id=document_id, storage_dir=self.storage_dir
            )
            self.assertEqual([r["revision_no"] for r in history], [1, 2])
            self.assertEqual([r["status"] for r in history], ["superseded", "active"])

            # The old revision is still fully readable: row + exact bytes.
            old = documents.get_revision(
                conn,
                revision_id=uuid.UUID(first["revision_id"]),
                storage_dir=self.storage_dir,
            )
            self.assertEqual(old["status"], "superseded")
            self.assertEqual(
                documents.read_revision_bytes(self.storage_dir, old["storage_key"]),
                first_body,
            )
            active = documents.get_document(
                conn, document_id=document_id, storage_dir=self.storage_dir
            )
            self.assertEqual(active["revision_count"], 2)
            self.assertEqual(active["active_revision"]["revision_no"], 2)
            self.assertEqual(
                active["active_revision"]["source_sha256"], _sha(second_body)
            )

    def test_identical_upload_is_idempotent(self) -> None:
        """Uploading the same bytes twice returns the tip, not a new row."""
        body = "相同內容\n".encode("utf-8")
        with self._connect_ready() as conn:
            document_id = self._document(conn)
            first = documents.upload_revision(
                conn,
                storage_dir=self.storage_dir,
                document_id=document_id,
                filename="wudi.txt",
                data=body,
            )
            second = documents.upload_revision(
                conn,
                storage_dir=self.storage_dir,
                document_id=document_id,
                filename="wudi.txt",
                data=body,
            )
            self.assertTrue(second["duplicate"])
            self.assertEqual(second["revision_id"], first["revision_id"])
            self.assertEqual(second["revision_no"], 1)
            history = documents.revision_history(
                conn, document_id=document_id, storage_dir=self.storage_dir
            )
            self.assertEqual(len(history), 1)

    def test_duplicate_repairs_a_missing_file(self) -> None:
        """A crash between commit and rename is repaired by retrying."""
        body = "修復測試\n".encode("utf-8")
        with self._connect_ready() as conn:
            document_id = self._document(conn)
            first = documents.upload_revision(
                conn,
                storage_dir=self.storage_dir,
                document_id=document_id,
                filename="wudi.txt",
                data=body,
            )
            # Simulate the interrupted write: row committed, file lost.
            Path(self.storage_dir, *first["storage_key"].split("/")).unlink()
            retry = documents.upload_revision(
                conn,
                storage_dir=self.storage_dir,
                document_id=document_id,
                filename="wudi.txt",
                data=body,
            )
            self.assertTrue(retry["duplicate"])
            self.assertEqual(retry["storage_status"], "present")
            self.assertEqual(
                documents.read_revision_bytes(self.storage_dir, retry["storage_key"]), body
            )

    def test_invalid_encoding_fails_without_side_effects(self) -> None:
        with self._connect_ready() as conn:
            document_id = self._document(conn)
            with self.assertRaises(PersistenceError):
                documents.upload_revision(
                    conn,
                    storage_dir=self.storage_dir,
                    document_id=document_id,
                    filename="scan.txt",
                    data=b"\xff\xfe\x00not-utf8",
                )
            history = documents.revision_history(
                conn, document_id=document_id, storage_dir=self.storage_dir
            )
            self.assertEqual(history, [])
            leftovers = list(self.storage_dir.rglob("*"))
            self.assertEqual(leftovers, [])

    def test_oversized_upload_fails_without_side_effects(self) -> None:
        with self._connect_ready() as conn:
            document_id = self._document(conn)
            with self.assertRaises(PersistenceError):
                documents.upload_revision(
                    conn,
                    storage_dir=self.storage_dir,
                    document_id=document_id,
                    filename="big.txt",
                    data=b"x" * 64,
                    max_bytes=16,
                )
            self.assertEqual(
                documents.revision_history(
                    conn, document_id=document_id, storage_dir=self.storage_dir
                ),
                [],
            )

    def test_unsafe_filename_and_format_fail(self) -> None:
        body = "ok\n".encode("utf-8")
        with self._connect_ready() as conn:
            document_id = self._document(conn)
            for bad_name in ("../evil.txt", "sub/dir.txt", "book.pdf", "archive.epub", ""):
                with self.assertRaises(PersistenceError, msg=bad_name):
                    documents.upload_revision(
                        conn,
                        storage_dir=self.storage_dir,
                        document_id=document_id,
                        filename=bad_name,
                        data=body,
                    )
            self.assertEqual(
                documents.revision_history(
                    conn, document_id=document_id, storage_dir=self.storage_dir
                ),
                [],
            )

    def test_unknown_document_fails_and_cleans_up(self) -> None:
        with self._connect_ready() as conn:
            with self.assertRaises(PersistenceError):
                documents.upload_revision(
                    conn,
                    storage_dir=self.storage_dir,
                    document_id=uuid.uuid4(),
                    filename="wudi.txt",
                    data="內容\n".encode("utf-8"),
                )
            # Staged temp bytes are removed; no visible files remain.
            leftovers = [p for p in self.storage_dir.rglob("*") if p.is_file()]
            self.assertEqual(leftovers, [])

    def test_revision_rows_stay_immutable(self) -> None:
        """C1-T1 immutability still holds after the C1-T3 columns land."""
        with self._connect_ready() as conn:
            document_id = self._document(conn)
            first = documents.upload_revision(
                conn,
                storage_dir=self.storage_dir,
                document_id=document_id,
                filename="wudi.txt",
                data="不可變\n".encode("utf-8"),
            )
            with self.assertRaises(Exception):
                with conn.transaction():
                    conn.execute(
                        "UPDATE chronicle.document_revisions SET filename = 'mutated.txt'"
                        " WHERE revision_id = %s",
                        (uuid.UUID(first["revision_id"]),),
                    )
            with self.assertRaises(Exception):
                with conn.transaction():
                    conn.execute(
                        "DELETE FROM chronicle.document_revisions WHERE revision_id = %s",
                        (uuid.UUID(first["revision_id"]),),
                    )

    def test_history_and_locator_support_chunk_provenance(self) -> None:
        body = "第一章\n內容甲\n".encode("utf-8")
        with self._connect_ready() as conn:
            document_id = self._document(conn)
            first = documents.upload_revision(
                conn,
                storage_dir=self.storage_dir,
                document_id=document_id,
                filename="wudi.txt",
                data=body,
                language="zh-CN",
                source_label="test-source",
            )
            listed = documents.list_documents(conn, storage_dir=self.storage_dir)
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["revision_count"], 1)
            self.assertEqual(listed[0]["active_revision_no"], 1)
            self.assertEqual(listed[0]["active_source_sha256"], _sha(body))

            locator = documents.source_locator(first)
            self.assertEqual(locator["source_sha256"], _sha(body))
            self.assertEqual(locator["source_bytes"], len(body))
            self.assertEqual((locator["source_start"], locator["source_end"]), (0, len(body)))
            # The locator round-trips to the exact stored bytes.
            self.assertEqual(
                documents.read_revision_bytes(
                    self.storage_dir, locator["storage_key"]
                ),
                body,
            )

    def test_unknown_document_and_revision_reads_fail(self) -> None:
        with self._connect_ready() as conn:
            with self.assertRaises(PersistenceError):
                documents.get_document(
                    conn, document_id=uuid.uuid4(), storage_dir=self.storage_dir
                )
            with self.assertRaises(PersistenceError):
                documents.revision_history(
                    conn, document_id=uuid.uuid4(), storage_dir=self.storage_dir
                )
            with self.assertRaises(PersistenceError):
                documents.get_revision(
                    conn, revision_id=uuid.uuid4(), storage_dir=self.storage_dir
                )

    def test_upgrade_from_c1t1_schema_backfills_and_keeps_immutability(self) -> None:
        """D-1: applying 0003 over a live 0002 database with rows succeeds.

        Reproduces the Reviewer failure: the 0002 forbid_revision_mutation
        trigger rejects application UPDATEs, so the 0003 backfill must park
        that trigger for its own upgrade statement and re-arm it. After the
        upgrade the legacy row carries deterministic defaults, the
        immutability guard still fires, and new C1-T3 uploads append cleanly.
        """
        migrations_dir = HERE / "migrations"
        # A database that stopped at 0002 with one live C1-T1 revision.
        legacy_document = uuid.uuid4()
        legacy_revision = uuid.uuid4()
        legacy_sha = _sha(b"legacy-bytes")
        for name in ("0001_chronicle_v0.sql", "0002_chronicle_c1_control_plane.sql"):
            raw = (migrations_dir / name).read_text(encoding="utf-8")
            with psycopg.connect(self.database_url) as setup_conn:
                with setup_conn.transaction():
                    setup_conn.execute(raw)
        with psycopg.connect(self.database_url) as setup_conn:
            with setup_conn.transaction():
                setup_conn.execute(
                    "INSERT INTO chronicle.documents(document_id, title)"
                    " VALUES (%s, %s)",
                    (legacy_document, "legacy"),
                )
                setup_conn.execute(
                    """
                    INSERT INTO chronicle.document_revisions(
                        revision_id, document_id, revision_no,
                        source_sha256, source_bytes, source_media_type,
                        supersedes_revision_id
                    ) VALUES (%s, %s, 1, %s, %s, %s, NULL)
                    """,
                    (
                        legacy_revision,
                        legacy_document,
                        legacy_sha,
                        len(b"legacy-bytes"),
                        "text/plain",
                    ),
                )
        # The real upgrade path under test: only 0003 is still pending.
        with psycopg.connect(self.database_url) as conn:
            apply_migrations(conn)
        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                """
                SELECT filename, storage_key, content_chars, language,
                       source_label, source_sha256, revision_no
                FROM chronicle.document_revisions
                WHERE revision_id = %s
                """,
                (legacy_revision,),
            ).fetchone()
            self.assertEqual(row[0], "upload.txt")
            self.assertEqual(
                row[1], f"documents/{legacy_document}/{legacy_revision}.txt"
            )
            self.assertEqual(row[2], 0)
            self.assertIsNone(row[3])
            self.assertIsNone(row[4])
            self.assertEqual(row[5], legacy_sha)
            # The immutability guard survived the upgrade: the backfill did
            # not leave the trigger parked or dropped.
            with self.assertRaises(Exception):
                with conn.transaction():
                    conn.execute(
                        "UPDATE chronicle.document_revisions SET filename = 'x'"
                        " WHERE revision_id = %s",
                        (legacy_revision,),
                    )
            with self.assertRaises(Exception):
                with conn.transaction():
                    conn.execute(
                        "DELETE FROM chronicle.document_revisions WHERE revision_id = %s",
                        (legacy_revision,),
                    )
            # New C1-T3 uploads append on the upgraded schema, superseding
            # the legacy tip non-destructively.
            second = documents.upload_revision(
                conn,
                storage_dir=self.storage_dir,
                document_id=legacy_document,
                filename="legacy.txt",
                data="legacy-bytes".encode("utf-8"),
            )
            self.assertTrue(second["duplicate"])
            self.assertEqual(second["revision_id"], str(legacy_revision))
            third = documents.upload_revision(
                conn,
                storage_dir=self.storage_dir,
                document_id=legacy_document,
                filename="legacy.txt",
                data="legacy-bytes-v2".encode("utf-8"),
            )
            self.assertEqual(third["revision_no"], 2)
            self.assertEqual(third["supersedes_revision_id"], str(legacy_revision))


if __name__ == "__main__":
    unittest.main()
