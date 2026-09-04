"""PostgreSQL 18 integration tests for the Studio document HTTP surface.

Exercises the real sidecar (ThreadingHTTPServer + handler_class) against
an isolated database and an isolated source-data directory: create
document, upload revisions, replacement/supersession, idempotent
duplicates, history/active queries, metadata + locator reads, raw content
reads, and safe failures (bad encoding, oversize, unsafe names, unknown
routes). This is the HTTP-level proof of the C1-T3 Studio contract; the
Rust proxy tests cover auth gating and byte passthrough separately.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
ROOT = HERE.parents[2]
for candidate in (str(HERE), str(PERSISTENCE)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from server import handler_class  # noqa: E402

from migrations import apply_migrations  # noqa: E402


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


class StudioDocumentsHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_c1t3_http_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        with psycopg.connect(self.database_url) as conn:
            apply_migrations(conn)
        self._tmp = tempfile.TemporaryDirectory(prefix="chronicle-c1t3-http-")
        handler = handler_class(
            self.database_url, Path(self._tmp.name), 1024 * 1024
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=10)
        self.server.server_close()
        self._tmp.cleanup()
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name))
            )

    # -- helpers ---------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> tuple[int, bytes, str]:
        request = Request(
            f"http://127.0.0.1:{self.port}{path}", data=body, method=method
        )
        if content_type:
            request.add_header("Content-Type", content_type)
        try:
            with urlopen(request, timeout=10) as response:
                return (
                    response.status,
                    response.read(),
                    response.headers.get("Content-Type", ""),
                )
        except HTTPError as exc:
            return exc.code, exc.read(), exc.headers.get("Content-Type", "")

    def _create_document(self, title="武帝紀") -> str:
        status, body, _ = self._request(
            "POST",
            "/api/v1/studio/documents",
            json.dumps({"title": title}).encode("utf-8"),
            "application/json",
        )
        self.assertEqual(status, 201, body)
        payload = json.loads(body)
        self.assertEqual(payload["schema"], "chronicle.document")
        return payload["document"]["document_id"]

    def _upload(
        self,
        document_id: str,
        filename: str,
        data: bytes,
        extra: str = "",
        content_type: str = "text/plain; charset=utf-8",
    ) -> tuple[int, dict]:
        query = {"filename": filename}
        path = (
            f"/api/v1/studio/documents/{document_id}/revisions"
            f"?{urllib.parse.urlencode(query)}{extra}"
        )
        status, body, _ = self._request("POST", path, data, content_type)
        return status, json.loads(body) if body else {}

    # -- tests -----------------------------------------------------------

    def test_create_upload_history_content_round_trip(self) -> None:
        document_id = self._create_document()
        body = "武帝紀第一\n".encode("utf-8")

        status, created = self._upload(document_id, "wudi.txt", body)
        self.assertEqual(status, 201, created)
        revision = created["revision"]
        self.assertEqual(revision["revision_no"], 1)
        self.assertEqual(revision["status"], "active")
        self.assertEqual(
            revision["source_sha256"], hashlib.sha256(body).hexdigest()
        )
        self.assertIn("locator", created)
        self.assertEqual(created["locator"]["source_end"], len(body))

        # History shows one active revision.
        status, raw, _ = self._request(
            "GET", f"/api/v1/studio/documents/{document_id}/revisions"
        )
        self.assertEqual(status, 200)
        history = json.loads(raw)["revisions"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["status"], "active")

        # Metadata by revision number and by UUID agree.
        for ref in ("1", revision["revision_id"]):
            status, raw, _ = self._request(
                "GET", f"/api/v1/studio/documents/{document_id}/revisions/{ref}"
            )
            self.assertEqual(status, 200, ref)
            payload = json.loads(raw)
            self.assertEqual(payload["revision"]["source_sha256"], revision["source_sha256"])
            self.assertEqual(payload["locator"]["revision_no"], 1)

        # Raw content is the exact uploaded bytes.
        status, raw, content_type = self._request(
            "GET",
            f"/api/v1/studio/documents/{document_id}/revisions/1/content",
        )
        self.assertEqual(status, 200)
        self.assertEqual(raw, body)
        self.assertIn("text/plain", content_type)

        # Document read exposes the active revision.
        status, raw, _ = self._request("GET", f"/api/v1/studio/documents/{document_id}")
        self.assertEqual(status, 200)
        document = json.loads(raw)["document"]
        self.assertEqual(document["revision_count"], 1)
        self.assertEqual(document["active_revision"]["revision_no"], 1)

        # List shows the document.
        status, raw, _ = self._request("GET", "/api/v1/studio/documents")
        self.assertEqual(status, 200)
        listed = json.loads(raw)["documents"]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["active_revision_no"], 1)

    def test_replacement_preserves_history(self) -> None:
        document_id = self._create_document()
        status, first = self._upload(document_id, "wudi.txt", "版本一\n".encode())
        self.assertEqual(status, 201)
        status, second = self._upload(document_id, "wudi.txt", "版本一\n版本二\n".encode())
        self.assertEqual(status, 201)
        self.assertEqual(second["revision"]["revision_no"], 2)

        status, raw, _ = self._request(
            "GET", f"/api/v1/studio/documents/{document_id}/revisions"
        )
        history = json.loads(raw)["revisions"]
        self.assertEqual(
            [(r["revision_no"], r["status"]) for r in history],
            [(1, "superseded"), (2, "active")],
        )
        # Old content still downloadable.
        status, raw, _ = self._request(
            "GET",
            f"/api/v1/studio/documents/{document_id}/revisions/1/content",
        )
        self.assertEqual(status, 200)
        self.assertEqual(raw, "版本一\n".encode("utf-8"))

    def test_duplicate_upload_returns_tip(self) -> None:
        document_id = self._create_document()
        body = "相同\n".encode("utf-8")
        status, first = self._upload(document_id, "wudi.txt", body)
        self.assertEqual(status, 201)
        status, second = self._upload(document_id, "wudi.txt", body)
        self.assertEqual(status, 200, second)
        self.assertTrue(second["revision"]["duplicate"])
        self.assertEqual(
            second["revision"]["revision_id"], first["revision"]["revision_id"]
        )

    def test_failures_are_safe_and_typed(self) -> None:
        document_id = self._create_document()
        # Invalid UTF-8.
        status, payload = self._upload(document_id, "bad.txt", b"\xff\xfe bad")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "bad_request")
        # Unsupported format.
        status, payload = self._upload(document_id, "book.pdf", b"%PDF fake")
        self.assertEqual(status, 400)
        # Unsafe filename.
        status, payload = self._upload(
            document_id, "../evil.txt", "x\n".encode(), extra=""
        )
        self.assertEqual(status, 400)
        # Content-Type mismatch.
        status, payload = self._upload(
            document_id, "wudi.txt", "x\n".encode(), content_type="text/markdown"
        )
        self.assertEqual(status, 400)
        # Empty body.
        status, payload = self._upload(document_id, "wudi.txt", b"")
        self.assertEqual(status, 400)
        # Missing filename.
        status, raw, _ = self._request(
            "POST",
            f"/api/v1/studio/documents/{document_id}/revisions",
            b"data",
            "text/plain",
        )
        self.assertEqual(status, 400)
        # Unknown document.
        status, payload = self._upload(str(uuid.uuid4()), "wudi.txt", "x\n".encode())
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")
        # Unknown revision.
        status, raw, _ = self._request(
            "GET",
            f"/api/v1/studio/documents/{document_id}/revisions/{uuid.uuid4()}",
        )
        self.assertEqual(status, 404)
        # Cross-document revision access is hidden.
        other = self._create_document("吳主傳")
        status, other_rev = self._upload(other, "wuzhu.txt", "孫權\n".encode())
        rev_id = other_rev["revision"]["revision_id"]
        status, raw, _ = self._request(
            "GET", f"/api/v1/studio/documents/{document_id}/revisions/{rev_id}"
        )
        self.assertEqual(status, 404)

    def test_oversized_upload_is_rejected(self) -> None:
        document_id = self._create_document()
        big = b"y" * (1024 * 1024 + 8)
        status, payload = self._upload(document_id, "big.txt", big)
        self.assertEqual(status, 413)
        self.assertEqual(payload["error"]["code"], "payload_too_large")

    def test_create_document_validates_title(self) -> None:
        for bad in ("", "   "):
            status, raw, _ = self._request(
                "POST",
                "/api/v1/studio/documents",
                json.dumps({"title": bad}).encode(),
                "application/json",
            )
            self.assertEqual(status, 400, repr(bad))
        status, raw, _ = self._request(
            "POST", "/api/v1/studio/documents", b"not-json", "application/json"
        )
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
